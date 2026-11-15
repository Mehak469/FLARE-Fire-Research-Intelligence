import unittest
from tests.helpers import fresh_db, run_id
from flare.core import coverage as cov, explore, compare, ranking, db as dbm
from flare.core.bins import AXES


class TestCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn, _ = fresh_db()

    def test_grid_sizes(self):
        self.assertEqual(len(cov.coverage(self.conn)["cells"]), 4 * 5)
        self.assertEqual(len(cov.coverage(self.conn, ("gravity_class",))["cells"]), 4)
        self.assertEqual(len(cov.coverage(self.conn, tuple(AXES))["cells"]), 4 * 5 * 4 * 4)

    def test_no_moon_or_mars_evidence_is_reported_as_gap(self):
        cells = cov.coverage(self.conn)["cells"]
        for g in ("lunar", "mars", "earth"):
            self.assertTrue(all(c["is_gap"] for c in cells if c["labels"]["gravity_class"] == g), g)

    def test_microgravity_cells_have_evidence(self):
        micro = {c["labels"]["o2_bin"]: c for c in cov.coverage(self.conn)["cells"] if c["labels"]["gravity_class"] == "micro"}
        self.assertEqual(micro["21-25"]["n_runs"], 10)        # all 10 loaded BASS-II runs start at 21 or 22.2 percent
        self.assertGreater(micro["21-25"]["n_investigations"], 3)
        self.assertEqual(micro["lt21"]["n_runs"], 0)

    def test_unmapped_is_reported_never_dropped(self):
        res = cov.coverage(self.conn)
        names = {u["name"] for u in res["unmapped"]["investigations"]}
        self.assertIn("SAFFIRE-III", names)                      # no stated oxygen range
        self.assertEqual(len(names), 10)
        four = cov.coverage(self.conn, tuple(AXES))["unmapped"]["runs"]
        self.assertEqual(four["count"], 10)                      # pressure and flow unknown for every loaded run
        self.assertEqual(four["by_missing_dim"]["pressure_bin"], 10)

    def test_verified_only_excludes_unverified(self):
        res = cov.coverage(self.conn, verified_only=True)
        self.assertEqual(sum(c["n_runs"] for c in res["cells"]), 0)

    def test_filters_and_validation(self):
        res = cov.coverage(self.conn, regime="droplet")
        self.assertLess(res["n_investigations_considered"], 20)
        with self.assertRaises(ValueError): cov.coverage(self.conn, ("nope",))
        with self.assertRaises(ValueError): cov.coverage(self.conn, ())

    def test_gravity_summary(self):
        g = cov.gravity_summary(self.conn)
        self.assertEqual(len(g["investigations"]["micro"]), 20)
        self.assertEqual(g["runs"]["micro"], 10)


class TestExplore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn, _ = fresh_db()

    def test_range_filter_counts_unknown_instead_of_hiding(self):
        res = explore.list_investigations(self.conn, o2=(20, 25))
        names = {i["name"] for i in res["items"]}
        self.assertIn("BASS-II", names); self.assertNotIn("SAME", names)
        self.assertEqual(res["excluded_unknown_range"]["o2_pct"], 10)

    def test_filters(self):
        self.assertTrue(all(i["regime"] == "droplet" for i in explore.list_investigations(self.conn, regime="droplet")["items"]))
        self.assertEqual({i["name"] for i in explore.list_investigations(self.conn, gravity_class="lunar")["items"]}, set())
        self.assertIn("SAME", {i["name"] for i in explore.list_investigations(self.conn, text="smoke aerosol")["items"]})

    def test_profile_has_labels_sources_and_honest_empty_findings(self):
        p = explore.get_profile(self.conn, "BASS-II")
        self.assertEqual(p["conditions"]["o2_pct"]["text"], "13.6 to 22.2 pct")
        self.assertEqual(p["conditions"]["pressure_kpa"]["text"], "not stated")
        self.assertIn("up to 40 cm/s", p["conditions"]["flow_cm_s"]["text"])
        self.assertTrue(all(s["evidence_label"] and "source" in s for s in p["sections"]))
        self.assertEqual(len(p["runs"]), 10); self.assertEqual(p["findings"], [])
        self.assertIsNone(explore.get_profile(self.conn, "NOPE"))

    def test_search_runs(self):
        self.assertEqual(len(explore.search_runs(self.conn, "BASS-II")), 10)
        self.assertEqual(len(explore.search_runs(self.conn, "BASS-II", o2=(22, 23))), 6)   # B1-B5 and B7 start at 22.2 percent; B6, B8-B10 at 21


class TestCompare(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn, _ = fresh_db()
        cls.b1, cls.b4, cls.b6 = (run_id(cls.conn, "BASS-II", x) for x in ("B1", "B4", "B6"))

    def test_b1_vs_b4(self):
        res = compare.compare_runs(self.conn, [self.b1, self.b4])
        d = {r["parameter"]: r for r in res["rows"]}
        self.assertEqual(d["thickness_mm"]["values"], [0.1, 0.3]); self.assertEqual(d["thickness_mm"]["status"], "different")
        self.assertEqual(d["o2_pct"]["status"], "same"); self.assertEqual(d["material"]["status"], "same")
        self.assertIn("cannot be established", res["summary"])
        self.assertTrue(all(r["group"] != "outcomes" for r in res["rows"]))   # nothing invented

    def test_negative_value_shown_as_stored(self):
        d = {r["parameter"]: r for r in compare.compare_runs(self.conn, [self.b1, self.b4])["rows"]}
        self.assertEqual(d["co_initial_ppm"]["values"], [0.0, -1.0])

    def test_three_runs_and_validation(self):
        self.assertEqual(len(compare.compare_runs(self.conn, [self.b1, self.b4, self.b6])["labels"]), 3)
        self.assertIn("error", compare.compare_runs(self.conn, [self.b1]))
        self.assertIn("error", compare.compare_runs(self.conn, [self.b1, 999999]))

    def test_different_regimes_refused(self):
        conn, _ = fresh_db()
        inv = dbm.scalar(conn, "SELECT investigation_id FROM investigations WHERE name='FLEX-2'")
        conn.execute("INSERT INTO runs(investigation_id,run_label) VALUES (?, 'FIXTURE-1')", (inv,))
        fx = dbm.scalar(conn, "SELECT run_id FROM runs WHERE run_label='FIXTURE-1'")
        res = compare.compare_runs(conn, [run_id(conn, "BASS-II", "B1"), fx])
        self.assertIn("different physical regimes", res["error"])

    def test_cross_investigation_settings_not_comparable(self):
        conn, _ = fresh_db()
        inv = dbm.scalar(conn, "SELECT investigation_id FROM investigations WHERE name='BASS'")   # same regime as BASS-II
        conn.execute("INSERT INTO runs(investigation_id,run_label) VALUES (?, 'FIXTURE-2')", (inv,))
        fx = dbm.scalar(conn, "SELECT run_id FROM runs WHERE run_label='FIXTURE-2'")
        conn.execute("INSERT INTO run_attributes(run_id,key,value_text) VALUES (?, 'fan_display', '47')", (fx,))
        res = compare.compare_runs(conn, [run_id(conn, "BASS-II", "B1"), fx])
        d = {r["parameter"]: r for r in res["rows"]}
        self.assertEqual(d["fan_display"]["status"], "not_comparable")

    def test_outcomes_reported_when_present(self):
        conn, _ = fresh_db()
        a, b = run_id(conn, "BASS-II", "B1"), run_id(conn, "BASS-II", "B4")
        mid = dbm.scalar(conn, "SELECT metric_id FROM metrics WHERE code='flame_spread_rate'")
        conn.execute("INSERT INTO measurements(run_id,metric_id,value_si,value_raw,unit_raw,extracted_by) VALUES (?,?,?,?,?,'manual')", (a, mid, 0.5, "FIXTURE 0.5", "mm/s"))
        res = compare.compare_runs(conn, [a, b])
        d = {r["parameter"]: r for r in res["rows"]}
        self.assertEqual(d["flame_spread_rate"]["status"], "missing_in_some")
        self.assertIn("flame_spread_rate", res["summary"])

    def test_compare_investigations(self):
        res = compare.compare_investigations(self.conn, ["BASS-II", "FLEX-2"])
        self.assertTrue(res["cross_regime"]); self.assertIn("different physical regimes", res["summary"])
        d = {r["parameter"]: r for r in res["rows"]}
        self.assertEqual(d["oxygen tested"]["values"], ["13.6 to 22.2 pct", "17 to 30 pct"])
        self.assertIn("error", compare.compare_investigations(self.conn, ["BASS-II"]))
        self.assertIn("error", compare.compare_investigations(self.conn, ["BASS-II", "NOPE"]))


class TestRanking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn, _ = fresh_db()

    def test_components_bounded_and_sorted(self):
        r = ranking.rank_investigations(self.conn, {"gravity_class": "micro", "o2": (21, 25)})
        self.assertEqual(len(r), 20)
        self.assertEqual([x["score"] for x in r], sorted((x["score"] for x in r), reverse=True))
        for x in r:
            self.assertTrue(all(0.0 <= v <= 1.0 for v in x["components"].values()), x["name"])
            self.assertGreaterEqual(x["score"], 0); self.assertLessEqual(x["score"], 100)

    def test_target_changes_condition_match_and_unknown_is_listed(self):
        lunar = {x["name"]: x for x in ranking.rank_investigations(self.conn, {"gravity_class": "lunar"})}
        self.assertTrue(all(x["components"]["condition_match"] == 0.0 for x in lunar.values()))
        o2 = {x["name"]: x for x in ranking.rank_investigations(self.conn, {"o2": (21, 25)})}
        self.assertIn("o2_pct", o2["SAFFIRE-III"]["unknown"])
        self.assertEqual(o2["SAFFIRE-III"]["components"]["condition_match"], 0.0)
        self.assertGreater(o2["BASS-II"]["components"]["condition_match"], 0.0)

    def test_evidence_strength_rises_with_runs_and_zero_without(self):
        r = {x["name"]: x for x in ranking.rank_investigations(self.conn)}
        self.assertEqual(r["SAFFIRE-I"]["components"]["evidence_strength"], 0.0)
        self.assertGreater(r["BASS-II"]["components"]["evidence_strength"], 0.0)
        self.assertEqual(r["BASS-II"]["components"]["outcome_availability"], 0.0)   # no outcome measurement is loaded
        self.assertIn("10 loaded run", r["BASS-II"]["explanation"])

    def test_deterministic(self):
        a = ranking.rank_investigations(self.conn, {"gravity_class": "micro"}); b = ranking.rank_investigations(self.conn, {"gravity_class": "micro"})
        self.assertEqual([(x["name"], x["score"]) for x in a], [(x["name"], x["score"]) for x in b])


if __name__ == "__main__":
    unittest.main()
