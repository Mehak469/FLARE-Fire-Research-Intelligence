"""Rendering of one investigation profile. Every fact shows an evidence chip, its source and a verification badge."""
from __future__ import annotations
import pandas as pd
import streamlit as st
from flare.ui import common


def render_profile(p: dict) -> None:
    inv = p["investigation"]
    st.markdown(f"### {inv['name']}: {inv['full_name']}")
    links = []
    if inv.get("psi_url"):
        links.append(f"[PSI record {inv.get('psi_id') or ''}]({inv['psi_url']})")
    if inv.get("doi"):
        links.append(f"[DOI {inv['doi']}](https://doi.org/{inv['doi']})")
    st.markdown("  |  ".join(links) if links else "No source link stored.")
    st.markdown(common.chip(inv["qa_status"]) + "  " + f"third-party status claim: {inv.get('third_party_status') or 'none'}", unsafe_allow_html=True)
    st.warning(p["third_party_note"])
    t_over, t_cond, t_runs, t_find, t_src = st.tabs(["Overview", "Conditions", "Runs", "Findings", "Sources and flags"])
    with t_over:
        for s in p["sections"]:
            st.markdown(f"**{s['title']}** " + common.chip(s["evidence_label"]) + "  " + common.chip(s["qa_status"]), unsafe_allow_html=True)
            st.write(s["text"])
            if s.get("source"):
                st.caption(f"Source: {s['source']}")
    with t_cond:
        rows = [{"quantity": {"o2_pct": "Oxygen (% by volume)", "pressure_kpa": "Pressure (kPa)", "flow_cm_s": "Airflow (cm/s)"}[q], "declared tested range": v["text"],
                 "status": v["qa_status"] or "not stated"} for q, v in p["conditions"].items()]
        rows.append({"quantity": "Gravity", "declared tested range": f"{p['gravity']['label'] or 'not stated'} (class: {p['gravity']['class']})", "status": inv["qa_status"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        st.caption("Ranges come from the investigation record, not from individual runs.")
    with t_runs:
        if p["runs"]:
            st.dataframe(pd.DataFrame(p["runs"]), hide_index=True)
        else:
            st.info("No individual runs are loaded for this investigation. Load its experimental table to enable run-level comparison.")
    with t_find:
        if p["findings"]:
            for f in p["findings"]:
                st.markdown(common.chip(f["evidence_label"]) + "  " + common.chip(f["qa_status"]), unsafe_allow_html=True)
                st.write(f["statement"])
                st.caption(f"{f['source_title']}, {f['source_ref']}. Quote: {f['quote']}")
                if f.get("limitations"):
                    st.caption(f"Limitations: {f['limitations']}")
        else:
            st.info("No curated findings are loaded for this investigation. Results require papers: see data/curated/findings.csv.")
    with t_src:
        st.dataframe(pd.DataFrame(p["sources"]), hide_index=True)
        if p["flags"]:
            st.warning("Open data flags (review against the source):")
            st.dataframe(pd.DataFrame(p["flags"]), hide_index=True)
