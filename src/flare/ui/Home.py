"""Screen 1: Explore. Coverage map, investigation explorer, ranking."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st
from flare import config
from flare.core import coverage as cov, db as dbm, explore, ranking
from flare.core.bins import AXES, AXIS_TITLES
from flare.ui import common
from flare.ui.charts import coverage_figure
from flare.ui.profile import render_profile

st.set_page_config(page_title="FLARE", layout="wide")
conn = common.require_conn()
common.header("FLARE: Fire Lab & Research Intelligence Engine",
              "Where NASA's loaded combustion research covers Moon and Mars conditions, and where it is silent.")

s = dbm.stats(conn)
for col, (label, key) in zip(st.columns(6), [("Investigations", "investigations"), ("Runs loaded", "runs"), ("Runs human-verified", "verified_runs"),
                                             ("Outcome measurements", "outcome_measurements"), ("Curated findings", "findings"), ("Paper pages", "paper_pages")]):
    col.metric(label, s[key])

tab_map, tab_explore, tab_rank = st.tabs(["Coverage map", "Explore investigations", "Ranking"])

# ---------------- coverage ----------------
with tab_map:
    refs = config.load_yaml("reference_conditions.yaml")
    st.subheader("Evidence coverage")
    b1, b2, b3 = st.columns(3)
    if b1.button("Moon-like"):
        st.session_state["preset"] = "moon"
    if b2.button("Mars-like"):
        st.session_state["preset"] = "mars"
    if b3.button("Clear preset"):
        st.session_state["preset"] = None
    preset = st.session_state.get("preset")

    c1, c2, c3 = st.columns(3)
    dims = c1.multiselect("Axes (first = rows, second = columns, third = panels)", list(AXES), default=["gravity_class", "o2_bin"],
                          format_func=lambda d: AXIS_TITLES[d], max_selections=3)
    mode = c2.selectbox("Count", ["investigations", "runs"], help="investigations: tested ranges declared in investigation records; runs: individual loaded tests")
    verified_only = c3.checkbox("Human-verified evidence only", value=False)
    if not dims:
        st.warning("Choose at least one axis.")
    else:
        result = cov.coverage(conn, tuple(dims), verified_only=verified_only)
        only = refs[preset]["gravity_class"] if preset and "gravity_class" in dims else None
        if preset:
            r = refs[preset]
            st.info(f"{r['label']} preset: gravity class '{r['gravity_class']}'. Cabin oxygen and pressure are not set "
                    f"({r.get('source')}): add values from an official NASA source in config/reference_conditions.yaml.")
            if "gravity_class" in dims:
                n_inv = sum(c["n_investigations"] for c in result["cells"] if c["labels"]["gravity_class"] == r["gravity_class"])
                n_run = sum(c["n_runs"] for c in result["cells"] if c["labels"]["gravity_class"] == r["gravity_class"])
                (st.error if n_inv + n_run == 0 else st.success)(f"Loaded evidence at {r['gravity_class']} gravity: {n_inv} investigation cell(s), {n_run} run(s).")
        st.plotly_chart(coverage_figure(result, mode=mode, only_gravity=only))
        st.caption(result["note"])
        um = result["unmapped"]
        st.warning(f"Not placed on this map: {len(um['investigations'])} of {result['n_investigations_considered']} investigations "
                   f"(a chosen quantity is not stated in their record) and {um['runs']['count']} of {result['n_runs_considered']} runs. "
                   "Missing information is not the same as missing evidence.")
        with st.expander("Which investigations are not placed, and why"):
            if um["investigations"]:
                st.dataframe(pd.DataFrame([{"investigation": u["name"], "unknown on": ", ".join(AXIS_TITLES[d] for d in u["missing_dims"])} for u in um["investigations"]]), hide_index=True)
            else:
                st.write("All investigations are placed on this map.")

# ---------------- explore ----------------
with tab_explore:
    st.subheader("Investigations")
    regimes = [r["code"] for r in dbm.q(conn, "SELECT DISTINCT r.code FROM investigations i JOIN regimes r ON r.regime_id=i.regime_id ORDER BY r.code")]
    f1, f2, f3, f4 = st.columns(4)
    regime = f1.selectbox("Physical regime", ["any"] + regimes)
    fuel = f2.selectbox("Fuel type", ["any", "solid", "liquid", "gas"])
    area = f3.selectbox("Safety area", ["any", "prevention", "suppression", "detection"])
    grav = f4.selectbox("Gravity class", ["any", "micro", "lunar", "mars", "earth"])
    text = st.text_input("Search text (objectives, fuels, hardware...)", "")
    r1, r2, r3 = st.columns(3)
    o2f = r1.slider("Oxygen % must overlap", 0.0, 100.0, (19.0, 35.0)) if r1.checkbox("Filter by oxygen") else None
    prf = r2.slider("Pressure kPa must overlap", 0.0, 600.0, (50.0, 110.0)) if r2.checkbox("Filter by pressure") else None
    flf = r3.slider("Airflow cm/s must overlap", 0.0, 100.0, (0.0, 30.0)) if r3.checkbox("Filter by airflow") else None
    res = explore.list_investigations(conn, regime=None if regime == "any" else regime, fuel_type=None if fuel == "any" else fuel,
                                      safety_area=None if area == "any" else area, gravity_class=None if grav == "any" else grav,
                                      o2=o2f, pressure=prf, flow=flf, text=text or None)
    st.write(f"{len(res['items'])} of {res['total_loaded']} loaded investigations match.")
    ex = res["excluded_unknown_range"]
    if any(ex.values()):
        st.warning("Hidden because the range filter needs a stated range: " + ", ".join(f"{k}: {v}" for k, v in ex.items() if v) +
                   ". Their records do not state it, which is not the same as not tested.")
    for it in res["items"]:
        with st.expander(f"{it['name']}  |  {it['regime']}  |  runs {it['n_runs']}, findings {it['n_findings']}"):
            st.write(it["full_name"])
            st.write(f"Oxygen tested: {it['ranges']['o2_pct']}  |  Pressure: {it['ranges']['pressure_kpa']}  |  Airflow: {it['ranges']['flow_cm_s']}")
            if it["psi_url"]:
                st.markdown(f"[PSI record]({it['psi_url']})")
    names = [i["name"] for i in res["items"]]
    if names:
        chosen = st.selectbox("Open full profile", names)
        profile = explore.get_profile(conn, chosen)
        if profile:
            render_profile(profile)

# ---------------- ranking ----------------
with tab_rank:
    st.subheader("Rank investigations by research evidence")
    st.caption("Ranks how well loaded evidence matches a target, not how dangerous anything is. Weights are product-design choices (config/ranking.yaml), not NASA coefficients.")
    t1, t2, t3, t4 = st.columns(4)
    tg = t1.selectbox("Target gravity", ["any", "micro", "lunar", "mars", "earth"])
    to2 = t2.slider("Target oxygen %", 0.0, 100.0, (21.0, 34.0)) if t2.checkbox("Target oxygen") else None
    tpr = t3.slider("Target pressure kPa", 0.0, 600.0, (50.0, 101.0)) if t3.checkbox("Target pressure") else None
    tfl = t4.slider("Target airflow cm/s", 0.0, 100.0, (0.0, 30.0)) if t4.checkbox("Target airflow") else None
    target = {k: v for k, v in {"gravity_class": None if tg == "any" else tg, "o2": to2, "pressure": tpr, "flow": tfl}.items() if v is not None}
    ranked = ranking.rank_investigations(conn, target)
    st.dataframe(pd.DataFrame([{"investigation": r["name"], "score": r["score"], "runs": r["n_runs"], "verified runs": r["n_verified_runs"],
                                "unknown": ", ".join(r["unknown"])} for r in ranked]), hide_index=True)
    for r in ranked[:5]:
        with st.expander(f"Why {r['name']} scored {r['score']}"):
            st.write(r["explanation"])

common.footer(conn)
