"""Ranking of investigations by research evidence. NOT a fire-danger ranking; weights are design choices (config/ranking.yaml)."""
from __future__ import annotations
import math
from .. import config
from . import db as dbm
from .bins import gravity_class, gravity_class_from_label


def _in_range(v, lo, hi) -> bool:
    return v is not None and (lo is None or v >= lo) and (hi is None or v <= hi)


def rank_investigations(conn, target: dict | None = None) -> list[dict]:
    """target keys (all optional): gravity_class, o2 (lo,hi), pressure (lo,hi), flow (lo,hi).

    Components (each 0..1): condition_match, evidence_strength, outcome_availability, applicability.
    Declared ranges give investigation-level matching; loaded runs refine it. Unknown values count as 0 and are listed.
    """
    cfg = config.load_yaml("ranking.yaml")
    w, sat = cfg["weights"], cfg["evidence_saturation_runs"]
    target = target or {}
    selected = [k for k in ("gravity_class", "o2", "pressure", "flow") if target.get(k) not in (None, (None, None))]
    out = []
    for inv in dbm.q(conn, "SELECT i.investigation_id, i.name, i.full_name, i.gravity_label, r.code AS regime FROM investigations i "
                           "LEFT JOIN regimes r ON r.regime_id=i.regime_id ORDER BY i.name"):
        iid = inv["investigation_id"]
        rng = {c["quantity"]: c for c in dbm.q(conn, "SELECT * FROM investigation_conditions WHERE investigation_id=?", (iid,))}
        runs = dbm.q(conn, "SELECT run_id, gravity_g, o2_pct, pressure_kpa, flow_cm_s, qa_status FROM runs WHERE investigation_id=? AND qa_status<>'rejected'", (iid,))
        n, v = len(runs), sum(1 for r in runs if r["qa_status"] == "human_verified")
        o = dbm.scalar(conn, "SELECT COUNT(DISTINCT m.run_id) FROM measurements m JOIN metrics x ON x.metric_id=m.metric_id JOIN runs r ON r.run_id=m.run_id "
                             "WHERE r.investigation_id=? AND x.is_outcome=1 AND r.qa_status<>'rejected'", (iid,)) or 0
        grav = gravity_class_from_label(inv["gravity_label"])
        unknown, scores = [], []
        for key in selected:
            if key == "gravity_class":
                if grav == "unknown": unknown.append("gravity"); scores.append(0.0)
                else: scores.append(1.0 if grav == target["gravity_class"] else 0.0)
                continue
            qty = {"o2": "o2_pct", "pressure": "pressure_kpa", "flow": "flow_cm_s"}[key]
            lo, hi = target[key]
            c = rng.get(qty)
            if not c:
                unknown.append(qty); scores.append(0.0); continue
            pts = [p for p in (c["min_value"], c["max_value"]) if p is not None]
            a, b = min(pts), max(pts)
            scores.append(1.0 if (a <= (hi if hi is not None else math.inf) and b >= (lo if lo is not None else -math.inf)) else 0.0)
        cm_inv = (sum(scores) / len(scores)) if scores else 1.0
        if n and selected:
            def inside(r):
                chk = []
                if "gravity_class" in selected: chk.append(gravity_class(r["gravity_g"]) == target["gravity_class"])
                for key, f in (("o2", "o2_pct"), ("pressure", "pressure_kpa"), ("flow", "flow_cm_s")):
                    if key in selected: chk.append(_in_range(r[f], *target[key]))
                return all(chk)
            cm = 0.5 * cm_inv + 0.5 * (sum(1 for r in runs if inside(r)) / n)
        else:
            cm = cm_inv
        es = (0.6 * min(1.0, math.log1p(n) / math.log1p(sat)) + 0.4 * (v / n)) if n else 0.0
        oa = (o / n) if n else 0.0
        ap = 1.0 if grav in ("micro", "lunar", "mars") else 0.0
        comps = {"condition_match": cm, "evidence_strength": es, "outcome_availability": oa, "applicability": ap}
        score = 100.0 * sum(w[k] * comps[k] for k in comps)
        expl = (f"Score {score:.0f}/100 = " + " + ".join(f"{k.replace('_', ' ')} {comps[k]:.2f} x {w[k] * 100:.0f}" for k in comps) +
                f". Based on {n} loaded run(s), {v} human-verified, {o} with an outcome measurement." +
                (f" Unknown for this investigation: {', '.join(unknown)} (counted as no match)." if unknown else ""))
        out.append({"name": inv["name"], "full_name": inv["full_name"], "regime": inv["regime"], "score": round(score, 1), "components": comps,
                    "n_runs": n, "n_verified_runs": v, "n_runs_with_outcome": o, "unknown": unknown, "explanation": expl})
    out.sort(key=lambda r: (-r["score"], r["name"]))
    return out
