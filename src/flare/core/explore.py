"""Explorer queries and investigation profiles. Every fact returned carries a label, a source and a verification status."""
from __future__ import annotations
from . import db as dbm, retrieval
from .bins import gravity_class_from_label

SECTION_META = {  # field -> (title, evidence label)
    "objective": ("Scientific objective", "hypothesis"),
    "variables": ("Variables studied", "configuration"),
    "fuel_detail": ("Fuels and samples", "configuration"),
    "hardware": ("Hardware", "configuration"),
    "sensors": ("Sensors", "configuration"),
    "relevance_note": ("Relevance note", "interpretation"),
    "earth_application": ("Earth application", "interpretation"),
}


def _ranges(conn) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for c in dbm.q(conn, "SELECT investigation_id, quantity, min_value, max_value, unit, qa_status FROM investigation_conditions"):
        out.setdefault(c["investigation_id"], {})[c["quantity"]] = c
    return out


def range_text(c: dict | None, quantity_label: str = "") -> str:
    if not c:
        return "not stated"
    lo, hi, unit = c["min_value"], c["max_value"], c["unit"]
    if lo is not None and hi is not None:
        return f"{lo:g} to {hi:g} {unit}" if lo != hi else f"{lo:g} {unit}"
    if hi is not None:
        return f"up to {hi:g} {unit} (lower end not stated)"
    return f"from {lo:g} {unit} (upper end not stated)"


def _overlaps(c: dict | None, lo: float | None, hi: float | None) -> bool | None:
    """True/False if the declared range overlaps [lo, hi]; None if the declared range is unknown."""
    if not c:
        return None
    pts = [p for p in (c["min_value"], c["max_value"]) if p is not None]
    a, b = min(pts), max(pts)
    lo = -float("inf") if lo is None else lo
    hi = float("inf") if hi is None else hi
    return a <= hi and b >= lo


def list_investigations(conn, regime: str | None = None, fuel_type: str | None = None, project: str | None = None,
                        safety_area: str | None = None, gravity_class: str | None = None,
                        o2: tuple | None = None, pressure: tuple | None = None, flow: tuple | None = None,
                        text: str | None = None) -> dict:
    """Filter investigations. A range filter excludes investigations whose range is not stated; they are counted, not hidden silently."""
    rows = dbm.q(conn, "SELECT s.*, i.full_name, i.psi_id, i.doi, i.fuel_type, i.safety_area, i.gravity_label, i.psi_url, i.qa_status, "
                       "i.third_party_status FROM v_investigation_stats s JOIN investigations i ON i.investigation_id=s.investigation_id ORDER BY s.name")
    rng = _ranges(conn)
    keep_ids = None
    if text:
        hits = retrieval.search_chunks(conn, text, k=60) + [{"investigation": r["investigation"]} for r in retrieval.search_findings(conn, text, k=30)]
        names = {h["investigation"] for h in hits if h.get("investigation")}
        keep_ids = names
    out, excluded = [], {"o2_pct": 0, "pressure_kpa": 0, "flow_cm_s": 0}
    for r in rows:
        if regime and r["regime"] != regime: continue
        if project and (r["program"] or "").lower() != project.lower(): continue
        if fuel_type and fuel_type not in (r["fuel_type"] or "").split("; ") and fuel_type not in (r["fuel_type"] or "").split(";"): continue
        if safety_area and safety_area not in (r["safety_area"] or "").replace(";", " ").split(): continue
        if gravity_class and gravity_class_from_label(r["gravity_label"]) != gravity_class: continue
        if keep_ids is not None and r["name"] not in keep_ids: continue
        bad = False
        for qty, flt in (("o2_pct", o2), ("pressure_kpa", pressure), ("flow_cm_s", flow)):
            if flt is None: continue
            ov = _overlaps(rng.get(r["investigation_id"], {}).get(qty), flt[0], flt[1])
            if ov is None: excluded[qty] += 1; bad = True
            elif not ov: bad = True
        if bad: continue
        r["ranges"] = {qty: range_text(rng.get(r["investigation_id"], {}).get(qty)) for qty in ("o2_pct", "pressure_kpa", "flow_cm_s")}
        out.append(r)
    return {"items": out, "excluded_unknown_range": excluded, "total_loaded": len(rows)}


def get_profile(conn, name: str) -> dict | None:
    inv = dbm.q1(conn, "SELECT i.*, r.code AS regime FROM investigations i LEFT JOIN regimes r ON r.regime_id=i.regime_id WHERE i.name=?", (name,))
    if not inv:
        return None
    sources = dbm.q(conn, "SELECT s.title, s.url, s.doi, s.source_type, s.retrieved_on FROM investigation_sources x JOIN sources s ON s.source_id=x.source_id "
                          "WHERE x.investigation_id=?", (inv["investigation_id"],))
    rec_src = next((s for s in sources if s["source_type"] == "psi_file" and s["url"]), None)
    sections = []
    for field, (title, label) in SECTION_META.items():
        txt = inv.get(field)
        if txt:
            sections.append({"field": field, "title": title, "text": txt, "evidence_label": label,
                             "source": (rec_src or {}).get("url"), "qa_status": inv["qa_status"]})
    conds = {c["quantity"]: c for c in dbm.q(conn, "SELECT * FROM investigation_conditions WHERE investigation_id=?", (inv["investigation_id"],))}
    runs = dbm.q(conn, "SELECT run_id, run_label, run_date, gravity_g, o2_pct, pressure_kpa, flow_cm_s, qa_status FROM runs "
                       "WHERE investigation_id=? AND qa_status <> 'rejected' ORDER BY run_id", (inv["investigation_id"],))
    findings = dbm.q(conn, "SELECT f.finding_id, f.statement, f.evidence_label, f.topic, f.quote, f.limitations, f.confidence, f.qa_status, f.source_ref, s.title AS source_title, s.url "
                           "FROM findings f JOIN sources s ON s.source_id=f.source_id WHERE f.investigation_id=? AND f.qa_status <> 'rejected'", (inv["investigation_id"],))
    flags = dbm.q(conn, "SELECT flag, detail, severity FROM data_flags WHERE resolved=0 AND ((table_name='investigations' AND row_id=?) OR "
                        "(table_name='runs' AND row_id IN (SELECT run_id FROM runs WHERE investigation_id=?)))", (inv["investigation_id"], inv["investigation_id"]))
    return {"investigation": inv, "sections": sections,
            "conditions": {q: {"text": range_text(conds.get(q)), "qa_status": (conds.get(q) or {}).get("qa_status")} for q in ("o2_pct", "pressure_kpa", "flow_cm_s")},
            "gravity": {"label": inv["gravity_label"], "class": gravity_class_from_label(inv["gravity_label"])},
            "runs": runs, "findings": findings, "sources": sources, "flags": flags,
            "third_party_note": "Investigation fields were compiled by a third party from NASA PSI records and are unverified; check the PSI link."}


def search_runs(conn, investigation: str | None = None, material: str | None = None, o2: tuple | None = None,
                qa_status: str | None = None, limit: int = 200, offset: int = 0) -> list[dict]:
    sql = ("SELECT run_id, investigation, run_label, material, geometry, thickness_mm, o2_pct, pressure_kpa, flow_cm_s, gravity_g, qa_status, source_ref "
           "FROM v_run_flat WHERE 1=1")
    params: list = []
    if investigation:
        sql += " AND investigation = ?"; params.append(investigation)
    if material:
        sql += " AND material = ?"; params.append(material)
    if o2 is not None:
        if o2[0] is not None: sql += " AND o2_pct >= ?"; params.append(o2[0])
        if o2[1] is not None: sql += " AND o2_pct <= ?"; params.append(o2[1])
    if qa_status:
        sql += " AND qa_status = ?"; params.append(qa_status)
    sql += " ORDER BY run_id LIMIT ? OFFSET ?"; params += [limit, offset]
    return dbm.q(conn, sql, params)
