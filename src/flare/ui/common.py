"""Shared Streamlit helpers. The UI reads only through flare.core (never raw files). Every number shown is computed live."""
from __future__ import annotations
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import streamlit as st  # noqa: E402
from flare import config  # noqa: E402
from flare.core import db as dbm  # noqa: E402

DISCLAIMER = ("FLARE is a research-evidence tool. It does not certify materials or conditions as safe or unsafe, and it does not predict fire risk. "
              "A gap means no evidence is loaded in this database, not that NASA has none.")

LABEL_STYLE = {   # evidence label -> (text, background, text color)
    "configuration": ("Configuration", "#E5E7EB", "#111827"),
    "measured_observation": ("Measured observation", "#DBEAFE", "#1E3A8A"),
    "published_finding": ("Published finding", "#DCFCE7", "#14532D"),
    "interpretation": ("Interpretation", "#FEF3C7", "#78350F"),
    "hypothesis": ("Objective / hypothesis", "#FEF3C7", "#78350F"),
    "unknown": ("Unknown", "#FFFFFF", "#991B1B"),
    "direct_experimental": ("Direct experimental evidence", "#DBEAFE", "#1E3A8A"),
    "published_interpretation": ("Published interpretation", "#DCFCE7", "#14532D"),
    "configuration_only": ("Configuration only", "#E5E7EB", "#111827"),
    "insufficient": ("Insufficient evidence", "#FFFFFF", "#991B1B"),
    "unverified": ("unverified", "#FEE2E2", "#991B1B"),
    "auto_checked": ("auto-checked", "#FEF3C7", "#78350F"),
    "human_verified": ("human-verified", "#DCFCE7", "#14532D"),
    "rejected": ("rejected", "#F3F4F6", "#6B7280"),
}


def chip(kind: str) -> str:
    text, bg, fg = LABEL_STYLE.get(kind, (kind, "#E5E7EB", "#111827"))
    border = "border:1px solid #991B1B;" if kind in ("unknown", "insufficient") else ""
    return f"<span style='background:{bg};color:{fg};padding:2px 8px;border-radius:10px;font-size:0.78rem;{border}'>{text}</span>"


@st.cache_resource
def _conn():
    return dbm.connect(check_same_thread=False)


def require_conn():
    """Return a database connection or stop the page with instructions."""
    if not Path(config.DB_PATH).exists():
        st.error("The database has not been built yet.")
        st.code("python -m flare.cli build-all", language="bash")
        st.stop()
    return _conn()


def header(title: str, subtitle: str = "") -> None:
    st.title(title)
    if subtitle:
        st.caption(subtitle)
    st.info(DISCLAIMER)


def footer(conn) -> None:
    s = dbm.stats(conn)
    st.divider()
    st.caption(f"Data status: {s['investigations']} investigation records, {s['runs']} runs ({s['verified_runs']} human-verified), "
               f"{s['findings']} curated findings, {s['paper_pages']} paper pages, {s['sources']} sources, {s['open_flags']} open data flags. "
               "Investigation records were compiled by a third party from NASA PSI and are unverified until a person checks them at the source link.")
