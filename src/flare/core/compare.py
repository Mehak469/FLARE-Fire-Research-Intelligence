"""Deterministic comparison (no LLM). Never infers an outcome from configuration data."""
from __future__ import annotations
import math
from . import db as dbm
from .bins import gravity_class_from_label
from .explore import range_text

GROUP_ORDER = ["configuration", "settings", "gas readings", "outcomes"]


def _same(vals: list) -> bool:
    first = vals[0]
    if all(isinstance(v, (int, float)) for v in vals):
        return all(math.isclose(v, first, rel_tol=1e-9, abs_tol=1e-12) for v in vals)
    return all(v == first for v in vals)


def _status(vals: list, comparable: bool = True) -> str:
    present = [v for v in vals if v is not None]
    if not present:
        return "absent"
    if not comparable:
        return "not_comparable"
    if len(present) < len(vals):
        return "missing_in_some"
    return "same" if _same(vals) else "different"


def _summarize(rows: list[dict], outcome_note: str) -> str:
    same = [r["parameter"] for r in rows if r["status"] == "same"]
    diff = [r["parameter"] for r in rows if r["status"] == "different"]
    miss = [r["parameter"] for r in rows if r["status"] == "missing_in_some"]
    parts = [f"{len(same)} shared, {len(diff)} different" + (f": {', '.join(diff)}" if diff else "") + "."]
    if miss:
        parts.append(f"Not stated for every item: {', '.join(miss)}.")
    parts.append(outcome_note)
    return " ".join(parts)


def compare_runs(conn, run_ids: list[int]) -> dict:
    if not 2 <= len(run_ids) <= 3:
        return {"error": "Choose two or three runs."}
    runs = []
    for rid in run_ids:
        r = dbm.q1(conn, "SELECT r.*, i.name AS inv, i.regime_id FROM runs r JOIN investigations i ON i.investigation_id=r.investigation_id WHERE r.run_id=?", (rid,))
        if not r:
            return {"error": f"Run {rid} not found."}
        runs.append(r)
    if len({r["regime_id"] for r in runs}) > 1:
        return {"error": "Not comparable: these runs belong to different physical regimes."}
    cross = len({r["inv"] for r in runs}) > 1
    params: dict[str, dict] = {}   # key -> {"group":..., "vals":[...]}

    def put(key, group, idx, val):
        params.setdefault(key, {"group": group, "vals": [None] * len(runs)})["vals"][idx] = val

    outcome_metrics = set()
    for i, r in enumerate(runs):
        for k in ("gravity_g", "o2_pct", "pressure_kpa", "flow_cm_s", "flow_mode", "temperature_k", "ignition_method", "run_date"):
            v = r[k]
            if v is not None and v != "unknown":
                put(k, "configuration", i, v)
        s = dbm.q(conn, "SELECT m.canonical_name AS material, s.geometry, s.thickness_mm, s.width_mm, s.length_mm, s.diameter_mm FROM samples s "
                        "JOIN materials m ON m.material_id=s.material_id WHERE s.run_id=? ORDER BY s.sample_id", (r["run_id"],))
        for k, v in (s[0] if s else {}).items():
            if v is not None:
                put(k, "configuration", i, v)
        if len(s) > 1:
            put("additional_samples", "configuration", i, f"{len(s) - 1} more")
        for a in dbm.q(conn, "SELECT key, value_text FROM run_attributes WHERE run_id=?", (r["run_id"],)):
            put(a["key"], "settings", i, a["value_text"])
        for m in dbm.q(conn, "SELECT x.code, x.is_outcome, m.value_si, m.qualifier FROM measurements m JOIN metrics x ON x.metric_id=m.metric_id WHERE m.run_id=?", (r["run_id"],)):
            grp = "outcomes" if m["is_outcome"] else "gas readings"
            if m["qualifier"] != "=":
                put(m["code"], grp, i, f"{m['qualifier']}{m['value_si']:g}")
            else:
                put(m["code"], grp, i, m["value_si"])
            if m["is_outcome"]:
                outcome_metrics.add(m["code"])
    rows = []
    for key, p in params.items():
        comparable = not (p["group"] == "settings" and cross)   # instrument settings from different investigations are not comparable
        rows.append({"parameter": key, "group": p["group"], "values": p["vals"], "status": _status(p["vals"], comparable)})
    rows = [r for r in rows if r["status"] != "absent"]
    rows.sort(key=lambda r: (GROUP_ORDER.index(r["group"]), r["parameter"]))
    outcome_note = ("Outcome measurements are loaded for: " + ", ".join(sorted(outcome_metrics)) + "." if outcome_metrics else
                    "No outcome measurements (for example flame spread rate) are loaded for these runs, so outcome differences cannot be established.")
    return {"kind": "runs", "labels": [f"{r['inv']} {r['run_label']}" for r in runs], "rows": rows,
            "provenance": [{"run": f"{r['inv']} {r['run_label']}", "source_ref": r["source_ref"], "qa_status": r["qa_status"]} for r in runs],
            "summary": _summarize(rows, outcome_note), "cross_investigation": cross}


def compare_investigations(conn, names: list[str]) -> dict:
    if not 2 <= len(names) <= 3:
        return {"error": "Choose two or three investigations."}
    invs = []
    for n in names:
        i = dbm.q1(conn, "SELECT i.*, r.code AS regime FROM investigations i LEFT JOIN regimes r ON r.regime_id=i.regime_id WHERE i.name=?", (n,))
        if not i:
            return {"error": f"Investigation {n!r} not found."}
        i["_ranges"] = {c["quantity"]: c for c in dbm.q(conn, "SELECT * FROM investigation_conditions WHERE investigation_id=?", (i["investigation_id"],))}
        i["_n_runs"] = dbm.scalar(conn, "SELECT COUNT(*) FROM runs WHERE investigation_id=? AND qa_status<>'rejected'", (i["investigation_id"],))
        invs.append(i)
    def ranged(i, q):
        c = i["_ranges"].get(q)
        return range_text(c) if c else None
    spec = [("regime", "configuration", lambda i: i["regime"]), ("fuel_type", "configuration", lambda i: i["fuel_type"]),
            ("gravity", "configuration", lambda i: gravity_class_from_label(i["gravity_label"]) if i["gravity_label"] else None),
            ("oxygen tested", "configuration", lambda i: ranged(i, "o2_pct")), ("pressure tested", "configuration", lambda i: ranged(i, "pressure_kpa")),
            ("airflow tested", "configuration", lambda i: ranged(i, "flow_cm_s")), ("safety area", "configuration", lambda i: i["safety_area"]),
            ("fuels and samples", "configuration", lambda i: i["fuel_detail"]), ("hardware", "settings", lambda i: i["hardware"]),
            ("sensors", "settings", lambda i: i["sensors"]), ("runs loaded here", "outcomes", lambda i: i["_n_runs"])]
    rows = []
    for key, grp, fn in spec:
        vals = [fn(i) for i in invs]
        st = _status(vals)
        if st != "absent":
            rows.append({"parameter": key, "group": grp, "values": vals, "status": st})
    regimes = {i["regime"] for i in invs}
    note = ("These investigations belong to different physical regimes, so their outcomes are not comparable. "
            if len(regimes) > 1 else "") + "This compares declared designs and ranges; it says nothing about outcomes."
    return {"kind": "investigations", "labels": names, "rows": rows, "summary": _summarize(rows, note), "cross_regime": len(regimes) > 1,
            "provenance": [{"investigation": i["name"], "source": i["psi_url"], "qa_status": i["qa_status"]} for i in invs]}
