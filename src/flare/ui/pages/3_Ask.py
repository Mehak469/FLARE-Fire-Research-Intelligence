"""Screen 3: Ask. Answers only from retrieved evidence; insufficient evidence is a normal result."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import streamlit as st
from flare.core import db as dbm
from flare.core.ask import ask
from flare.ui import common

st.set_page_config(page_title="FLARE: Ask", layout="wide")
conn = common.require_conn()
common.header("Ask", "Answers come only from loaded sources, with citations. If the data cannot answer, FLARE says so.")

invs = dbm.q(conn, "SELECT investigation_id, name FROM investigations ORDER BY name")
with_range = dbm.q(conn, "SELECT i.name FROM investigations i JOIN investigation_conditions c ON c.investigation_id=i.investigation_id WHERE c.quantity='o2_pct' ORDER BY i.name LIMIT 1")
examples = []
if with_range:
    examples.append(f"What oxygen levels did {with_range[0]['name']} test?")
examples += ["Has anything been tested at Moon gravity?", "Which test had the higher flame-spread rate?"]
cols = st.columns(len(examples))
for col, ex in zip(cols, examples):
    if col.button(ex):
        st.session_state["q"] = ex

question = st.text_input("Your question", value=st.session_state.get("q", ""))
scope = st.multiselect("Limit to investigations (optional)", [i["name"] for i in invs])
if st.button("Ask") and question.strip():
    ids = [i["investigation_id"] for i in invs if i["name"] in scope] or None
    res = ask(conn, question, investigation_ids=ids)
    if res["mode"] == "refused":
        st.warning(res["summary"])
    elif res["insufficient"]:
        st.markdown(common.chip("insufficient"), unsafe_allow_html=True)
        st.error(res["summary"])
    else:
        if res["mode"] == "extractive":
            st.info("Showing retrieved evidence without AI synthesis.")
        st.subheader("Answer")
        st.write(res["summary"])
        for c in res["claims"]:
            st.markdown(common.chip(c["evidence_label"]), unsafe_allow_html=True)
            st.write(c["text"])
            st.caption("Evidence: " + ", ".join(c["evidence_ids"]))
    for lim in res["limitations"]:
        st.caption("Limitation: " + lim)
    if res["evidence"]:
        with st.expander(f"Evidence used ({len(res['evidence'])})"):
            for e in res["evidence"]:
                st.markdown(f"**{e['id']}** ({e['kind']})")
                st.write(e["text"])
                st.caption(e.get("citation", ""))
common.footer(conn)
