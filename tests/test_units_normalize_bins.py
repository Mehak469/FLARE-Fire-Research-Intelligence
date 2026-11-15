import math
import unittest
from tests.helpers import fresh_db
from flare.core import units, normalize as nz, bins


class TestUnits(unittest.TestCase):
    def test_known_conversions(self):
        self.assertAlmostEqual(units.convert(1, "psi", "pressure")[0], 6.89476)
        self.assertAlmostEqual(units.convert(1, "atm", "pressure")[0], 101.325)
        self.assertAlmostEqual(units.convert(2.5, "m/s", "speed")[0], 250)
        self.assertAlmostEqual(units.convert(100, "micron", "length")[0], 0.1)
        self.assertAlmostEqual(units.convert(1, "cm/s", "spread_rate")[0], 10)
        self.assertAlmostEqual(units.convert(0, "C", "temperature")[0], 273.15)
        self.assertAlmostEqual(units.convert(212, "F", "temperature")[0], 373.15)
        self.assertAlmostEqual(units.convert(9.80665, "m/s2", "gravity")[0], 1.0)
        self.assertAlmostEqual(units.convert(0.21, "fraction", "oxygen")[0], 21.0)

    def test_unknown_never_guesses(self):
        v, flag = units.convert(5, "furlong", "length")
        self.assertIsNone(v); self.assertIn("unknown", flag)
        self.assertIsNone(units.convert(5, None, "length")[0])
        self.assertEqual(units.convert(None, "kPa", "pressure"), (None, None))

    def test_partial_pressure_needs_total(self):
        self.assertAlmostEqual(units.o2_pct_from_partial_pressure(21.2, 101.3)[0], 20.93, places=1)
        self.assertIsNone(units.o2_pct_from_partial_pressure(21.2, None)[0])


class TestNormalize(unittest.TestCase):
    def test_fuel_variants(self):
        a = nz.parse_fuel_text("100 micron PMMA film 2 cm wide")
        self.assertEqual((a["material"], a["thickness_mm"], a["width_mm"], a["flags"]), ("PMMA", 0.1, 20.0, []))
        b = nz.parse_fuel_text("2 cm 0.1 mm PMMA film")
        self.assertEqual((b["thickness_mm"], b["width_mm"]), (0.1, 20.0))
        c = nz.parse_fuel_text("1 cm 0.2 mm PMMA film")
        self.assertEqual((c["thickness_mm"], c["width_mm"]), (0.2, 10.0))

    def test_missing_material_is_flagged_not_silent(self):
        d = nz.parse_fuel_text("100 micron film 2 cm wide")
        self.assertIsNone(d["material"]); self.assertIn("material_not_found", d["flags"])
        e = nz.parse_fuel_text("100 micron film 2 cm wide", default_material="PMMA")
        self.assertEqual(e["material"], "PMMA"); self.assertIn("material_inferred", e["flags"])

    def test_numbers_and_dates(self):
        self.assertIsNone(nz.parse_number("")); self.assertIsNone(nz.parse_number("none")); self.assertEqual(nz.parse_number("-1"), -1.0)
        d = nz.parse_date_mdy("2/19/2014")
        self.assertEqual(nz.day_of_year(d), 50)
        self.assertEqual(nz.day_of_year(nz.parse_date_mdy("7/7/2014")), 188)


class TestBinsMatchSql(unittest.TestCase):
    """bins.py and the SQL view v_run_bins must agree, otherwise the map and the database disagree."""
    def test_equivalence(self):
        conn, _ = fresh_db(with_runs=False)
        inv = conn.execute("SELECT investigation_id FROM investigations LIMIT 1").fetchone()[0]
        grid = {"gravity_g": [None, 0, 0.005, 0.17, 0.38, 0.5, 1.0],
                "o2_pct": [None, 13, 20.99, 21, 24.9, 25, 29.9, 30, 39.9, 40, 85],
                "pressure_kpa": [None, 10, 59.9, 60, 94.9, 95, 109.9, 110, 300],
                "flow_cm_s": [None, 0, 0.1, 9.9, 10, 29.9, 30, 40]}
        n = 0
        for col, vals in grid.items():
            for v in vals:
                n += 1
                conn.execute(f"INSERT INTO runs(investigation_id,run_label,{col}) VALUES (?,?,?)", (inv, f"T{n}", v))
                row = conn.execute("SELECT gravity_class,o2_bin,pressure_bin,flow_bin FROM v_run_bins WHERE run_id=last_insert_rowid()").fetchone()
                py = (bins.gravity_class(v if col == "gravity_g" else None), bins.o2_bin(v if col == "o2_pct" else None),
                      bins.pressure_bin(v if col == "pressure_kpa" else None), bins.flow_bin(v if col == "flow_cm_s" else None))
                self.assertEqual(tuple(row), py, f"{col}={v}")

    def test_overlap(self):
        self.assertEqual(bins.bins_overlapping(21.5, 21.7, bins.O2_BINS), ["21-25"])
        self.assertEqual(bins.bins_overlapping(13.6, 22.2, bins.O2_BINS), ["lt21", "21-25"])
        self.assertEqual(bins.bins_overlapping(None, 40, bins.FLOW_BINS), ["gte30"])      # one-ended: only the stated point
        self.assertEqual(bins.bins_overlapping(None, None, bins.FLOW_BINS), [])
        self.assertEqual(bins.gravity_class_from_label("microgravity"), "micro")
        self.assertEqual(bins.gravity_class_from_label("something else"), "unknown")


if __name__ == "__main__":
    unittest.main()
