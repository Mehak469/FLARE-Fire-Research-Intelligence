"""Data status, verification and open flags. Honest limits live here."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pandas as pd
import streamlit as st
from flare.core import db as dbm
from flare.ui import common

st.set_page_config(page_title="FLARE: Data quality", layout="wide")
conn = common.require_conn()
common.header("Data and verification status")
s = dbm.stats(conn)
st.dataframe(pd.DataFrame([{"item": k.replace("_", " "), "count": v} for k, v in s.items()]), hide_index=True)
st.subheader("Verification of runs")
st.dataframe(pd.DataFrame(dbm.q(conn, "SELECT qa_status, COUNT(*) AS runs FROM runs GROUP BY qa_status")), hide_index=True)
st.subheader("Open data flags")
flags = dbm.q(conn, "SELECT f.table_name, f.row_id, f.flag, f.severity, f.detail FROM data_flags f WHERE f.resolved=0 ORDER BY f.severity, f.flag")
st.dataframe(pd.DataFrame(flags), hide_index=True) if flags else st.success("No open flags.")
st.subheader("Sources")
st.dataframe(pd.DataFrame(dbm.q(conn, "SELECT source_key, source_type, title, url, retrieved_on, substr(sha256,1,12) AS checksum FROM sources ORDER BY source_id")), hide_index=True)
st.subheader("Data completeness per investigation")
st.dataframe(pd.DataFrame(dbm.q(conn, "SELECT name, n_runs, n_verified_runs, n_runs_with_outcome, n_findings, n_sources FROM v_investigation_stats ORDER BY name")), hide_index=True)
common.footer(conn)
