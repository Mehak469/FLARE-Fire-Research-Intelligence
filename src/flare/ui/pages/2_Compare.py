"""Screen 2: Compare. Deterministic; only compatible parameters; never infers outcomes."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pandas as pd
import streamlit as st
from flare.core import compare, db as dbm, explore
from flare.ui import common

st.set_page_config(page_title="FLARE: Compare", layout="wide")
conn = common.require_conn()
common.header("Compare", "Two or three items side by side. Only compatible parameters are compared; outcomes are never inferred from settings.")

STATUS = {"same": "same", "different": "DIFFERENT", "missing_in_some": "not stated for all", "not_comparable": "not comparable"}


def show(res: dict) -> None:
    if res.get("error"):
        st.error(res["error"]); return
    cols = ["Parameter", "Group"] + res["labels"] + ["Status"]
    rows = [[r["parameter"], r["group"]] + [("-" if v is None else v) for v in r["values"]] + [STATUS.get(r["status"], r["status"])] for r in res["rows"]]
    st.dataframe(pd.DataFrame(rows, columns=cols).astype(str), hide_index=True)
    st.markdown("**Summary** " + res["summary"])
    with st.expander("Provenance"):
        st.dataframe(pd.DataFrame(res["provenance"]).astype(str), hide_index=True)


kind = st.radio("Compare", ["Investigations (declared designs and ranges)", "Runs (individual tests)"], horizontal=True)
if kind.startswith("Investigations"):
    names = [r["name"] for r in dbm.q(conn, "SELECT name FROM investigations ORDER BY name")]
    pick = st.multiselect("Choose two or three investigations", names, max_selections=3)
    if len(pick) >= 2:
        show(compare.compare_investigations(conn, pick))
    else:
        st.info("Pick at least two.")
else:
    runs = explore.search_runs(conn, limit=1000)
    if not runs:
        st.info("No runs are loaded. Load an experimental table first: python -m flare.cli ingest-table <mapping> <file>")
    else:
        label_to_id = {f"{r['investigation']} {r['run_label']} ({r['material']}, {r['thickness_mm']} mm, O2 {r['o2_pct']}%)": r["run_id"] for r in runs}
        pick = st.multiselect("Choose two or three runs", list(label_to_id), max_selections=3)
        if len(pick) >= 2:
            show(compare.compare_runs(conn, [label_to_id[p] for p in pick]))
        else:
            st.info("Pick at least two.")
common.footer(conn)
