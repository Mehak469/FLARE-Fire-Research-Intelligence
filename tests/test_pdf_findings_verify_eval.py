import tempfile
import unittest
import uuid
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from tests.helpers import fresh_db, run_id, ROOT
from flare.core import db as dbm, retrieval
from flare.core.evaluation import run_eval
from flare.ingest.findings_import import import_findings
from flare.ingest.inventory import build_inventory
from flare.ingest.pdf_text import chunk_text, ingest_pdf
from flare.ingest.verify import validate, verify_investigation_record, verify_runs

PAGE1 = "FIXTURE PAPER page one. The test section used a small flow duct and a radiometer."
PAGE2 = "FIXTURE PAPER page two. In this fixture the spread was recorded at a value that exists only in this test document."


def make_pdf() -> Path:
    path = Path(tempfile.gettempdir()) / f"fixture_{uuid.uuid4().hex}.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    for text in (PAGE1, PAGE2):
        c.drawString(50, 780, text[:80]); c.drawString(50, 760, text[80:]); c.showPage()
    c.showPage()   # a blank third page: must be flagged, not crash
    c.save()
    return path


class TestPdfAndFindings(unittest.TestCase):
    def setUp(self):
        self.conn, _ = fresh_db()
        self.pdf = make_pdf()
        self.rep = ingest_pdf(self.conn, self.pdf, "fixture-paper", title="FIXTURE paper", url="https://example.invalid/fixture", investigation="BASS-II")

    def write_csv(self, rows):
        p = Path(tempfile.gettempdir()) / f"f_{uuid.uuid4().hex}.csv"
        head = "investigation,statement,evidence_label,topic,source_key,page,quote,limitations,confidence\n"
        p.write_text(head + "\n".join(rows) + "\n", encoding="utf-8"); return p

    def test_pages_chunks_and_flag(self):
        self.assertEqual(self.rep["pages"], 3); self.assertEqual(self.rep["pages_without_text"], [3])
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM doc_pages WHERE source_id=(SELECT source_id FROM sources WHERE source_key='fixture-paper')"), 2)
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM data_flags WHERE flag='page_without_text'"), 1)
        pages = {r["page"] for r in dbm.q(self.conn, "SELECT page FROM doc_chunks WHERE section IS NULL")}
        self.assertEqual(pages, {1, 2})    # chunks never cross pages

    def test_paper_text_is_searchable_with_page_citation(self):
        items = retrieval.search_chunks(self.conn, "spread recorded value fixture document")
        self.assertTrue(items[0]["is_paper"]); self.assertEqual(items[0]["page"], 2); self.assertIn("page 2", items[0]["citation"])

    def test_reingest_is_idempotent(self):
        n = dbm.scalar(self.conn, "SELECT COUNT(*) FROM doc_chunks")
        ingest_pdf(self.conn, self.pdf, "fixture-paper", title="FIXTURE paper", investigation="BASS-II")
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM doc_chunks"), n)
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM doc_chunks_fts"), n)

    def test_findings_quote_validation(self):
        good = 'BASS-II,Fixture statement,published_finding,fixture_topic,fixture-paper,2,"the spread was recorded at a value that exists only in this",Fixture limit,high'
        wrong_page = 'BASS-II,Statement B,published_finding,t,fixture-paper,1,"spread was recorded at a value",,'
        invented = 'BASS-II,Statement C,published_finding,t,fixture-paper,2,"flame spread of 9.9 mm/s was observed",,'
        no_src = 'BASS-II,Statement D,published_finding,t,missing-paper,2,"anything",,'
        bad_label = 'BASS-II,Statement E,great_finding,t,fixture-paper,2,"spread was recorded",,'
        rep = import_findings(self.conn, self.write_csv([good, wrong_page, invented, no_src, bad_label]))
        self.assertEqual((rep["inserted"], len(rep["rejected"])), (1, 4))
        reasons = " ".join(r["reason"] for r in rep["rejected"])
        for expect in ("quote not found", "not found; ingest the paper first", "evidence_label"):
            self.assertIn(expect, reasons)
        f = dbm.q1(self.conn, "SELECT qa_status, page, evidence_label FROM findings")
        self.assertEqual((f["qa_status"], f["page"]), ("unverified", 2))
        self.assertEqual(import_findings(self.conn, self.write_csv([good]))["skipped_existing"], 1)

    def test_findings_become_retrievable_and_unlock_published_labels(self):
        import_findings(self.conn, self.write_csv(['BASS-II,Fixture statement about spread,published_finding,fixture_topic,fixture-paper,2,"spread was recorded at a value",,']))
        from flare.core import ask as askmod
        r = askmod.ask(self.conn, "What was recorded about spread in the fixture?", use_llm=False)
        self.assertEqual(r["claims"][0]["evidence_ids"][0][0], "F")
        self.assertEqual(r["claims"][0]["evidence_label"], "published_interpretation")
        self.assertFalse(any("results cannot be stated" in l for l in r["limitations"]))

    def test_chunk_text(self):
        t = " ".join(["word"] * 600)
        parts = chunk_text(t, 900, 150)
        self.assertTrue(all(len(p) <= 900 for p in parts)); self.assertGreater(len(parts), 2)
        self.assertEqual(chunk_text(""), [])


class TestVerification(unittest.TestCase):
    def setUp(self):
        self.conn, _ = fresh_db()

    def test_validate_promotes_only_clean_runs_and_never_to_human(self):
        rep = validate(self.conn)
        self.assertTrue(all(c["ok"] for c in rep["checks"]))
        self.assertEqual(rep["auto_checked"], 5)     # B2, B3, B4, B5, B7 carry flags
        status = {r["run_label"]: r["qa_status"] for r in dbm.q(self.conn, "SELECT run_label, qa_status FROM runs")}
        self.assertEqual(status["B1"], "auto_checked"); self.assertEqual(status["B4"], "unverified")
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM runs WHERE qa_status='human_verified'"), 0)

    def test_human_verify_requires_apply_and_resolves_flags_only_when_accepted(self):
        shown = verify_runs(self.conn, "BASS-II", ["B1", "B4"], "tester")
        self.assertEqual(shown[1]["status"], "shown"); self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM runs WHERE qa_status='human_verified'"), 0)
        blocked = verify_runs(self.conn, "BASS-II", ["B4"], "tester", apply=True)
        self.assertTrue(blocked[0]["status"].startswith("blocked"))
        ok = verify_runs(self.conn, "BASS-II", ["B1", "B4"], "tester", accept_flags=True, apply=True)
        self.assertEqual([x["status"] for x in ok], ["human_verified", "human_verified"])
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM data_flags f JOIN runs r ON r.run_id=f.row_id WHERE f.table_name='runs' AND r.run_label='B4' AND f.resolved=0"), 0)
        log = dbm.q1(self.conn, "SELECT actor, new_value FROM edit_log ORDER BY log_id DESC")
        self.assertEqual((log["actor"], log["new_value"]), ("tester", "human_verified"))
        self.assertEqual(verify_runs(self.conn, "BASS-II", ["ZZ"], "t")[0]["status"], "not found")

    def test_verified_run_changes_coverage_and_ranking(self):
        from flare.core import coverage as cov, ranking
        before = ranking.rank_investigations(self.conn)
        verify_runs(self.conn, "BASS-II", ["B1"], "t", accept_flags=True, apply=True)
        cells = cov.coverage(self.conn, verified_only=True)["cells"]
        self.assertEqual(sum(c["n_verified_runs"] for c in cells), 1)
        after = {r["name"]: r for r in ranking.rank_investigations(self.conn)}
        self.assertGreater(after["BASS-II"]["components"]["evidence_strength"], {r["name"]: r for r in before}["BASS-II"]["components"]["evidence_strength"])

    def test_record_verification(self):
        self.assertTrue(verify_investigation_record(self.conn, "BASS-II", "tester"))
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM investigation_conditions c JOIN investigations i USING(investigation_id) WHERE i.name='BASS-II' AND c.qa_status<>'human_verified'"), 0)
        self.assertFalse(verify_investigation_record(self.conn, "NOPE", "t"))


class TestEvalAndInventory(unittest.TestCase):
    def test_all_evaluation_cases_pass_offline(self):
        conn, _ = fresh_db()
        rep = run_eval(conn, write_report=False)
        self.assertEqual(rep["failed"], 0, [r for r in rep["results"] if not r["ok"]])
        self.assertGreaterEqual(len(rep["results"]), 14)
        self.assertEqual({r["category"] for r in rep["results"]}, {"answerable", "unanswerable", "adversarial"})

    def test_inventory_lists_data_files(self):
        out = Path(tempfile.gettempdir()) / f"inv_{uuid.uuid4().hex}.md"
        text = build_inventory(out)
        self.assertIn("investigations.json", text); self.assertIn("20 data rows", text)


if __name__ == "__main__":
    unittest.main()
