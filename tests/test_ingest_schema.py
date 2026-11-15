import sqlite3
import unittest
from pathlib import Path
from tests.helpers import fresh_db, ROOT
from flare.core import db as dbm
from flare.ingest.investigations import ingest_investigations
from flare.ingest.table_loader import load_table


class TestInvestigations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn, _ = fresh_db(with_runs=False)

    def test_counts_and_ids(self):
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM investigations"), 20)
        row = dbm.q1(self.conn, "SELECT psi_id, doi FROM investigations WHERE name='SAFFIRE-III'")
        self.assertEqual(row["psi_id"], "PSI-100")
        self.assertTrue(row["doi"].startswith("10.60555/"))

    def test_regime_assigned_for_all(self):
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM investigations WHERE regime_id IS NULL"), 0)
        self.assertEqual(dbm.q1(self.conn, "SELECT r.code c FROM investigations i JOIN regimes r USING(regime_id) WHERE i.name='FLEX-2'")["c"], "droplet")

    def test_blank_ranges_stay_missing(self):
        # SAFFIRE-III has no stated oxygen range in the record: there must be NO o2 row (never 0)
        n = dbm.scalar(self.conn, "SELECT COUNT(*) FROM investigation_conditions c JOIN investigations i USING(investigation_id) WHERE i.name='SAFFIRE-III' AND quantity='o2_pct'")
        self.assertEqual(n, 0)
        one = dbm.q1(self.conn, "SELECT min_value, max_value FROM investigation_conditions c JOIN investigations i USING(investigation_id) WHERE i.name='BASS-II' AND quantity='flow_cm_s'")
        self.assertIsNone(one["min_value"]); self.assertEqual(one["max_value"], 40.0)

    def test_everything_unverified_and_sourced(self):
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM investigations WHERE qa_status<>'unverified'"), 0)
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM investigations i WHERE NOT EXISTS (SELECT 1 FROM investigation_sources s WHERE s.investigation_id=i.investigation_id)"), 0)
        self.assertGreater(dbm.scalar(self.conn, "SELECT COUNT(*) FROM sources WHERE sha256 IS NOT NULL"), 0)

    def test_idempotent(self):
        before = (dbm.scalar(self.conn, "SELECT COUNT(*) FROM doc_chunks"), dbm.scalar(self.conn, "SELECT COUNT(*) FROM data_flags"),
                  dbm.scalar(self.conn, "SELECT COUNT(*) FROM sources"))
        ingest_investigations(self.conn)
        after = (dbm.scalar(self.conn, "SELECT COUNT(*) FROM doc_chunks"), dbm.scalar(self.conn, "SELECT COUNT(*) FROM data_flags"),
                 dbm.scalar(self.conn, "SELECT COUNT(*) FROM sources"))
        self.assertEqual(before, after)


class TestTableLoader(unittest.TestCase):
    def setUp(self):
        self.conn, _ = fresh_db(with_runs=True)

    def test_loaded_counts(self):
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM runs"), 10)
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM samples"), 10)
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM measurements"), 48)   # 50 minus 2 blank cells in B2

    def test_blank_cells_make_no_measurement(self):
        n = dbm.scalar(self.conn, "SELECT COUNT(*) FROM measurements m JOIN runs r USING(run_id) JOIN metrics x USING(metric_id) WHERE r.run_label='B2' AND x.code IN ('co2_final_pct','co_final_ppm')")
        self.assertEqual(n, 0)

    def test_anomalies_flagged_not_fixed(self):
        flags = {(r["label"], r["flag"]) for r in dbm.q(self.conn, "SELECT r.run_label label, f.flag FROM data_flags f JOIN runs r ON r.run_id=f.row_id WHERE f.table_name='runs'")}
        for expect in [("B2", "o2_large_change"), ("B4", "negative_gas"), ("B3", "material_inferred"), ("B5", "material_inferred"), ("B7", "material_inferred")]:
            self.assertIn(expect, flags)
        neg = dbm.scalar(self.conn, "SELECT m.value_si FROM measurements m JOIN runs r USING(run_id) JOIN metrics x USING(metric_id) WHERE r.run_label='B4' AND x.code='co_initial_ppm'")
        self.assertEqual(neg, -1.0)   # kept as written, never clipped
        self.assertEqual(dbm.scalar(self.conn, "SELECT o2_pct FROM runs WHERE run_label='B2'"), 22.2)

    def test_day_of_year_cross_check_passes_for_real_rows(self):
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM data_flags WHERE flag='date_vs_day_of_year'"), 0)

    def test_unknown_pressure_and_flow_stay_null(self):
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM runs WHERE pressure_kpa IS NOT NULL OR flow_cm_s IS NOT NULL"), 0)
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM run_attributes WHERE key='fan_display'"), 10)

    def test_rerun_skips_existing(self):
        rep = load_table(self.conn, ROOT / "config/mappings/bass2.yaml", ROOT / "data/staging/bass2_staging_sample.csv")
        self.assertEqual((rep["loaded"], rep["skipped_existing"]), (0, 10))
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM runs"), 10)

    def test_raw_row_and_source_kept(self):
        r = dbm.q1(self.conn, "SELECT raw_record, source_id, source_ref FROM runs WHERE run_label='B6'")
        self.assertIn("153m", r["raw_record"]); self.assertIsNotNone(r["source_id"]); self.assertIn("test B6", r["source_ref"])

    def test_missing_columns_reported_not_guessed(self):
        bad = Path(self.conn.execute("PRAGMA database_list").fetchone()[2]).with_suffix(".csv")
        bad.write_text("Test #,Date\nB1,2/19/2014\n", encoding="utf-8")
        rep = load_table(self.conn, ROOT / "config/mappings/bass2.yaml", bad) if False else None
        # an unknown run label in a file with missing columns loads a run but reports every missing column
        self.conn.execute("DELETE FROM runs WHERE run_label='B1'")
        rep = load_table(self.conn, ROOT / "config/mappings/bass2.yaml", bad)
        self.assertIn("Fuel Sample Material", rep["missing_columns"])
        self.assertEqual(rep["loaded"], 1)


class TestSchemaConstraints(unittest.TestCase):
    def setUp(self):
        self.conn, _ = fresh_db(with_runs=False)
        self.inv = dbm.scalar(self.conn, "SELECT investigation_id FROM investigations LIMIT 1")

    def test_check_constraints(self):
        for col, val in (("o2_pct", 150), ("pressure_kpa", -5), ("flow_cm_s", -1), ("gravity_g", 9)):
            with self.assertRaises(sqlite3.IntegrityError, msg=col):
                self.conn.execute(f"INSERT INTO runs(investigation_id,run_label,{col}) VALUES (?,?,?)", (self.inv, "X", val))

    def test_unique_and_foreign_keys(self):
        self.conn.execute("INSERT INTO runs(investigation_id,run_label) VALUES (?, 'U1')", (self.inv,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO runs(investigation_id,run_label) VALUES (?, 'U1')", (self.inv,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO runs(investigation_id,run_label) VALUES (99999, 'U2')")

    def test_range_constraint(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO investigation_conditions(investigation_id,quantity,min_value,max_value,unit) VALUES (?,?,?,?,?)", (self.inv, "pressure_kpa", 50, 10, "kPa"))
        with self.assertRaises(sqlite3.IntegrityError):   # both ends NULL is not a range
            self.conn.execute("INSERT INTO investigation_conditions(investigation_id,quantity,unit) VALUES (?,?,?)", (self.inv, "pressure_kpa", "kPa"))

    def test_fts_stays_in_sync_after_delete(self):
        n = dbm.scalar(self.conn, "SELECT COUNT(*) FROM doc_chunks")
        self.conn.execute("DELETE FROM doc_chunks WHERE chunk_id=(SELECT MIN(chunk_id) FROM doc_chunks)")
        self.assertEqual(dbm.scalar(self.conn, "SELECT COUNT(*) FROM doc_chunks_fts"), n - 1)

    def test_init_db_refuses_overwrite(self):
        _, path = fresh_db(with_runs=False)
        with self.assertRaises(FileExistsError):
            dbm.init_db(path)


if __name__ == "__main__":
    unittest.main()
