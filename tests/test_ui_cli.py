"""Executes every Streamlit page script against the real test database using a stand-in for streamlit/plotly (the real packages
are not available in the build sandbox). This catches broken imports, wrong function names, SQL errors and unhandled states."""
import io
import os
import runpy
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tests import ui_stub
from tests.helpers import fresh_db, ROOT
from flare import config


class UiBase(unittest.TestCase):
    PAGES = {"home": "src/flare/ui/Home.py", "compare": "src/flare/ui/pages/2_Compare.py",
             "ask": "src/flare/ui/pages/3_Ask.py", "quality": "src/flare/ui/pages/4_Data_Quality.py"}

    @classmethod
    def setUpClass(cls):
        conn, path = fresh_db(with_validate=True)
        conn.close()
        cls.path = path
        cls._old = (config.DB_PATH, dict(sys.modules))
        config.DB_PATH = path
        from flare.core import db as dbm
        cls.dbm = dbm

    @classmethod
    def tearDownClass(cls):
        config.DB_PATH = cls._old[0]
        for k in ("streamlit", "plotly", "plotly.graph_objects", "plotly.subplots"):
            sys.modules.pop(k, None)
        for k in [m for m in sys.modules if m.startswith("flare.ui")]:
            sys.modules.pop(k, None)

    def run_page(self, key, press=(), checked=(), pick_n=0, text=None, state=None):
        for k in [m for m in sys.modules if m.startswith("flare.ui")]:
            sys.modules.pop(k, None)
        ui_stub.reset()
        ui_stub.CONFIG.update({"press": set(press), "checked": set(checked), "pick_n": pick_n, "text": text or {}})
        st, log = ui_stub.install()
        st.session_state.update(state or {})
        try:
            runpy.run_path(str(ROOT / self.PAGES[key]), run_name="__main__")
        except ui_stub.StopPage:
            pass
        return st, log


class TestPages(UiBase):
    def names(self, log): return [c[0] for c in log]

    def test_home_default(self):
        st, log = self.run_page("home")
        n = self.names(log)
        self.assertIn("plotly_chart", n); self.assertIn("metric", n); self.assertIn("warning", n)     # coverage + counts + unmapped warning
        metrics = [c[1] for c in log if c[0] == "metric"]
        self.assertEqual(dict(metrics)["Investigations"], 20); self.assertEqual(dict(metrics)["Runs loaded"], 10)

    def test_home_moon_preset_reports_no_evidence(self):
        st, log = self.run_page("home", press={"Moon-like"})
        self.assertEqual(st.session_state["preset"], "moon")
        errors = [c[1][0] for c in log if c[0] == "error"]
        self.assertTrue(any("0 investigation cell(s), 0 run(s)" in e for e in errors), errors)
        infos = [c[1][0] for c in log if c[0] == "info"]
        self.assertTrue(any("TODO_CONFIRM" in i for i in infos))

    def test_home_with_filters_and_profile(self):
        st, log = self.run_page("home", checked={"Filter by oxygen", "Filter by airflow", "Target oxygen"})
        n = self.names(log)
        self.assertIn("selectbox", n); self.assertIn("dataframe", n)
        self.assertTrue(any(c[0] == "tabs" and "Overview" in c[1][0] for c in log), "profile tabs were not rendered")
        self.assertTrue(any(c[0] == "warning" and "third party" in c[1][0] for c in log), "third-party provenance warning missing")

    def test_home_three_axes_and_runs_mode(self):
        self.run_page("home")   # default axes
        # the figure builder supports 3 axes without error
        from flare.core import coverage as cov, db as dbm
        from flare.ui.charts import coverage_figure
        conn = dbm.connect()
        coverage_figure(cov.coverage(conn, ("gravity_class", "o2_bin", "pressure_bin")), mode="runs")
        coverage_figure(cov.coverage(conn, ("o2_bin",)), mode="investigations")
        with self.assertRaises(ValueError):
            coverage_figure(cov.coverage(conn, tuple(__import__("flare.core.bins", fromlist=["AXES"]).AXES)))

    def test_compare_investigations_and_runs(self):
        st, log = self.run_page("compare", pick_n=2)
        self.assertIn("dataframe", self.names(log)); self.assertNotIn("error", self.names(log))
        st, log = self.run_page("compare", pick_n=2)
        # switch to the runs view by making the radio pick the second option
        orig = ui_stub.Container.radio
        ui_stub.Container.radio = lambda self, label, options, index=0, **k: options[1]
        try:
            st, log = self.run_page("compare", pick_n=2)
        finally:
            ui_stub.Container.radio = orig
        self.assertIn("dataframe", self.names(log)); self.assertNotIn("error", self.names(log))

    def test_compare_prompts_when_fewer_than_two(self):
        st, log = self.run_page("compare", pick_n=0)
        self.assertTrue(any(c[0] == "info" and "at least two" in c[1][0] for c in log))

    def test_ask_answers_and_refuses(self):
        st, log = self.run_page("ask", press={"Ask"}, text={"Your question": "What hardware did BASS-II use?"}, state={"q": "What hardware did BASS-II use?"})
        n = self.names(log); self.assertIn("subheader", n); self.assertIn("expander", n)
        st, log = self.run_page("ask", press={"Ask"}, text={"Your question": "Is PMMA safe?"})
        self.assertTrue(any(c[0] == "warning" and "does not certify" in c[1][0] for c in log))
        st, log = self.run_page("ask", press={"Ask"}, text={"Your question": "Which test had the higher flame spread rate?"})
        self.assertTrue(any(c[0] == "error" and "cannot answer" in c[1][0] for c in log))

    def test_data_quality_page(self):
        st, log = self.run_page("quality")
        self.assertIn("dataframe", self.names(log))

    def test_missing_database_shows_instructions(self):
        old = config.DB_PATH; config.DB_PATH = Path("/nonexistent/flame.db")
        try:
            st, log = self.run_page("quality")
        finally:
            config.DB_PATH = old
        self.assertTrue(any(c[0] == "error" and "not been built" in c[1][0] for c in log))


class TestCli(unittest.TestCase):
    def test_build_all_ask_and_stats(self):
        from flare import cli
        conn, path = fresh_db(with_runs=False); conn.close()
        old = config.DB_PATH; config.DB_PATH = path
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(cli.main(["ingest-table", str(ROOT / "config/mappings/bass2.yaml"), str(ROOT / "data/staging/bass2_staging_sample.csv")]), 0)
                self.assertEqual(cli.main(["stats"]), 0)
                self.assertEqual(cli.main(["ask", "Has anything been tested at Moon gravity?", "--offline"]), 0)
                self.assertEqual(cli.main(["validate"]), 0)
                self.assertEqual(cli.main(["verify", "--investigation", "BASS-II", "--labels", "B1", "--by", "t"]), 0)
            out = buf.getvalue()
            self.assertIn('"runs": 10', out); self.assertIn("0 labeled lunar", out)
        finally:
            config.DB_PATH = old


if __name__ == "__main__":
    unittest.main()
