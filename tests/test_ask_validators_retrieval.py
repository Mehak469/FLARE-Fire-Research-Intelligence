import json
import unittest
from tests.helpers import fresh_db
from flare.core import ask as askmod, db as dbm, retrieval, validators
from flare.core.llm import LLMError, get_client


class Fake:
    name = "fake"
    def __init__(self, out=None, err=None): self.out, self.err, self.calls = out, err, 0
    def complete_json(self, system, user, max_tokens=1200):
        self.calls += 1
        if self.err: raise self.err
        return self.out


class TestRetrieval(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn, _ = fresh_db()

    def test_operators_in_user_text_are_harmless(self):
        for q in ['oxygen AND (flame OR NOT "x")*', "'; DROP TABLE runs; --", "NEAR(a b)", '"unbalanced', "*", ""]:
            retrieval.search_chunks(self.conn, q); retrieval.search_findings(self.conn, q)
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM runs"), 10)

    def test_relevant_chunks_found_with_citation(self):
        items = retrieval.search_chunks(self.conn, "What hardware did BASS-II use?", k=3)
        self.assertEqual(items[0]["investigation"], "BASS-II")
        self.assertIn("psi.nasa.gov", items[0]["citation"])

    def test_irrelevant_returns_nothing(self):
        self.assertEqual(retrieval.search_chunks(self.conn, "quantum chromodynamics gluon"), [])

    def test_investigation_mentions(self):
        names = [m["name"] for m in retrieval.mentioned_investigations(self.conn, "Compare SAFFIRE-III with BASS-II and psi-26")]
        self.assertEqual(set(names), {"SAFFIRE-III", "BASS-II", "BASS"})
        self.assertEqual([m["name"] for m in retrieval.mentioned_investigations(self.conn, "FLEX-2 only")], ["FLEX-2"])   # not also FLEX


class TestValidators(unittest.TestCase):
    PACK = [{"id": "D1", "kind": "condition", "text": "BASS-II declared tested ranges: oxygen 13.6 to 22.2 pct; airflow up to 40 cm/s.", "citation": "PSI record (https://x/PSI-25)"},
            {"id": "F1", "kind": "finding", "evidence_label": "published_finding", "text": "Flame spread slowed at 10 cm/s.", "citation": "paper p4"},
            {"id": "M1", "kind": "measurement", "text": "spread 0.8 mm/s", "citation": "table"}]

    def ans(self, text, ids=("D1",), label="configuration_only", insufficient=False):
        return {"insufficient": insufficient, "summary": "s", "limitations": [], "claims": [] if insufficient else [{"text": text, "evidence_ids": list(ids), "evidence_label": label}]}

    def ok(self, a): return validators.validate_answer(a, self.PACK)

    def test_good(self):
        self.assertTrue(self.ok(self.ans("BASS-II tested oxygen from 13.6 to 22.2 pct."))[0])
        self.assertTrue(self.ok(self.ans("Oxygen was 22.2 pct (PSI-25) in O2 terms.", ))[0])

    def test_rejections(self):
        self.assertFalse(self.ok(self.ans("tested 25 pct"))[0])                                  # number absent
        self.assertFalse(self.ok(self.ans("x", ids=("Z9",)))[0])                                 # unknown id
        self.assertFalse(self.ok(self.ans("x", ids=()))[0])                                      # no citation
        self.assertFalse(self.ok(self.ans("tested 22.2", label="direct_experimental"))[0])       # label too strong for config evidence
        self.assertTrue(self.ok(self.ans("spread 0.8 mm/s", ids=("M1",), label="direct_experimental"))[0])
        self.assertFalse(self.ok(self.ans("PMMA is safe at 22.2 pct"))[0])                       # safety claim
        self.assertFalse(self.ok(self.ans("it will ignite at 22.2 pct"))[0])
        self.assertFalse(self.ok(self.ans("see PSI-99 at 22.2"))[0])                             # id not in evidence
        self.assertFalse(self.ok({"insufficient": False})[0])
        self.assertFalse(self.ok({"insufficient": True, "summary": "s", "limitations": [], "claims": [{"text": "x", "evidence_ids": ["D1"], "evidence_label": "configuration_only"}]})[0])
        self.assertTrue(self.ok(self.ans("", insufficient=True))[0])

    def test_label_helpers(self):
        self.assertEqual(validators.evidence_label_for(self.PACK[1]), "published_interpretation")
        self.assertEqual(validators.evidence_label_for(self.PACK[2]), "direct_experimental")
        self.assertEqual(validators.evidence_label_for(self.PACK[0]), "configuration_only")


class TestAsk(unittest.TestCase):
    def setUp(self):
        self.conn, _ = fresh_db()

    def ask(self, q, **k): return askmod.ask(self.conn, q, use_llm=False, **k)

    def test_policy_refusals(self):
        for q in ["Is PMMA safe for a Moon base?", "Certify Nomex as safe", "What is the probability of fire on Mars?", "Will it ignite at 30% oxygen?", "Is it safe to use SIBAL?"]:
            r = self.ask(q); self.assertEqual(r["mode"], "refused", q); self.assertTrue(r["insufficient"])
        self.assertNotEqual(self.ask("What safety areas did SAME address?")["mode"], "refused")   # the word 'safety' is fine

    def test_missing_metric_is_insufficient_and_lists_available(self):
        r = self.ask("Which test had the higher flame spread rate, B1 or B4?")
        self.assertEqual(r["mode"], "insufficient"); self.assertIn("co_final_ppm", " ".join(r["limitations"]))
        self.assertEqual(r["claims"], [])

    def test_metric_becomes_answerable_once_loaded(self):
        a = dbm.scalar(self.conn, "SELECT r.run_id FROM runs r WHERE run_label='B1'")
        mid = dbm.scalar(self.conn, "SELECT metric_id FROM metrics WHERE code='flame_spread_rate'")
        self.conn.execute("INSERT INTO measurements(run_id,metric_id,value_si,value_raw,unit_raw,extracted_by) VALUES (?,?,?,?,?,'manual')", (a, mid, 0.5, "FIXTURE", "mm/s"))
        self.assertNotEqual(self.ask("What is the flame spread rate in test B1?")["mode"], "insufficient")

    def test_gravity_question_is_structured_and_computed(self):
        r = self.ask("Has anything been tested at lunar gravity?")
        self.assertEqual(r["mode"], "structured")
        self.assertIn("20 labeled microgravity", r["claims"][0]["text"]); self.assertIn("0 labeled lunar", r["claims"][0]["text"])
        self.assertEqual(len(r["claims"][0]["evidence_ids"]), 20)

    def test_every_claim_is_cited_and_labeled(self):
        for q in ["What oxygen levels did BASS-II test?", "What fuels were used in SAFFIRE-I?", "Which investigations studied smoke detection?"]:
            r = self.ask(q); ids = {e["id"] for e in r["evidence"]}
            self.assertTrue(r["claims"], q)
            for c in r["claims"]:
                self.assertTrue(c["evidence_ids"] and set(c["evidence_ids"]) <= ids)
                self.assertEqual(c["evidence_label"], "configuration_only")    # no results are loaded, so nothing stronger may be claimed
            self.assertTrue(any("results cannot be stated" in l for l in r["limitations"]))

    def test_named_test_lookup(self):
        r = self.ask("What was the fuel and thickness in test B4?")
        self.assertIn("thickness 0.3 mm", r["claims"][0]["text"]); self.assertEqual(r["claims"][0]["evidence_ids"][0][0], "R")

    def test_nothing_relevant(self):
        self.assertTrue(self.ask("quantum chromodynamics")["insufficient"]); self.assertTrue(self.ask("   ")["insufficient"])

    def test_scope_filter(self):
        ids = [dbm.scalar(self.conn, "SELECT investigation_id FROM investigations WHERE name='SAFFIRE-I'")]
        r = self.ask("What fuels were used?", investigation_ids=ids)
        self.assertTrue(all((e.get("investigation") in (None, "SAFFIRE-I")) for e in r["evidence"]))

    def test_llm_valid_answer_is_accepted(self):
        d = askmod.build_pack(self.conn, "What oxygen levels did BASS-II test?")
        did = [p["id"] for p in d if p["id"].startswith("D")][0]
        good = {"insufficient": False, "summary": "Range", "limitations": [], "claims": [{"text": "BASS-II declared oxygen 13.6 to 22.2 pct.", "evidence_ids": [did], "evidence_label": "configuration_only"}]}
        fake = Fake(good); r = askmod.ask(self.conn, "What oxygen levels did BASS-II test?", client=fake)
        self.assertEqual((r["mode"], r["validation"], fake.calls), ("llm", "passed", 1))

    def test_llm_invalid_answer_retries_then_falls_back(self):
        bad = {"insufficient": False, "summary": "x", "limitations": [], "claims": [{"text": "It is safe at 99 pct.", "evidence_ids": ["D2"], "evidence_label": "direct_experimental"}]}
        fake = Fake(bad); r = askmod.ask(self.conn, "What oxygen levels did BASS-II test?", client=fake)
        self.assertEqual(fake.calls, 2); self.assertEqual(r["mode"], "extractive"); self.assertTrue(r["validation"].startswith("failed"))
        self.assertNotIn("safe at 99", json.dumps(r["claims"]))

    def test_llm_error_falls_back_without_crashing(self):
        r = askmod.ask(self.conn, "What oxygen levels did BASS-II test?", client=Fake(err=LLMError("network down")))
        self.assertEqual(r["mode"], "extractive"); self.assertTrue(any("unavailable" in l for l in r["limitations"]))

    def test_every_question_is_logged(self):
        n = dbm.scalar(self.conn, "SELECT COUNT(*) FROM ask_log")
        self.ask("What oxygen levels did BASS-II test?"); self.ask("Is PMMA safe?")
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM ask_log"), n + 2)

    def test_offline_is_default_client(self):
        self.assertIsNone(get_client())


if __name__ == "__main__":
    unittest.main()
