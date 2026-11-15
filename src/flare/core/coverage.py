"""Evidence coverage map.

Two kinds of evidence are counted separately and never mixed:
  * investigation-level: the tested RANGE declared in an investigation record (o2, pressure, flow, gravity label)
  * run-level: individual loaded runs (e.g. BASS-II tests)
A cell with zero of both is a GAP: "no loaded evidence here", not "NASA has none".
Evidence with an unknown value on a chosen axis cannot be placed on that map: it is reported as UNMAPPED, never dropped.
"""
from __future__ import annotations
import itertools
from . import db as dbm
from .bins import (AXES, O2_BINS, PRESSURE_BINS, FLOW_BINS, AXIS_QUANTITY, bins_overlapping,
                   gravity_class, gravity_class_from_label, o2_bin, pressure_bin, flow_bin)

_BIN_DEFS = {"o2_bin": O2_BINS, "pressure_bin": PRESSURE_BINS, "flow_bin": FLOW_BINS}
_RUN_BIN_FN = {"o2_bin": o2_bin, "pressure_bin": pressure_bin, "flow_bin": flow_bin}
_RUN_FIELD = {"o2_bin": "o2_pct", "pressure_bin": "pressure_kpa", "flow_bin": "flow_cm_s"}


def _inv_axis_labels(inv: dict, ranges: dict, dim: str) -> tuple[list[str], bool]:
    """Labels an investigation occupies on one axis; (labels, partial). Unknown -> ([], False)."""
    if dim == "gravity_class":
        c = gravity_class_from_label(inv.get("gravity_label"))
        return ([] if c == "unknown" else [c]), False
    qty = AXIS_QUANTITY[dim]
    r = ranges.get(qty)
    if not r:
        return [], False
    lo, hi = r
    partial = (lo is None) != (hi is None)   # only one end stated: we only claim the stated point
    return bins_overlapping(lo, hi, _BIN_DEFS[dim]), partial


def coverage(conn, dims: tuple[str, ...] = ("gravity_class", "o2_bin"), verified_only: bool = False,
             regime: str | None = None, fuel_type: str | None = None) -> dict:
    for d in dims:
        if d not in AXES:
            raise ValueError(f"unknown axis {d!r}; choose from {list(AXES)}")
    if not 1 <= len(dims) <= 4:
        raise ValueError("choose 1 to 4 axes")
    axes = {d: list(AXES[d]) for d in dims}

    sql = ("SELECT i.investigation_id, i.name, i.gravity_label, i.fuel_type, i.qa_status, r.code AS regime "
           "FROM investigations i LEFT JOIN regimes r ON r.regime_id=i.regime_id WHERE 1=1")
    params: list = []
    if regime:
        sql += " AND r.code = ?"; params.append(regime)
    if fuel_type:
        sql += " AND (';'||COALESCE(i.fuel_type,'')||';') LIKE ?"; params.append(f"%;{fuel_type};%")
    invs = dbm.q(conn, sql, params)
    ranges: dict[int, dict] = {}
    for c in dbm.q(conn, "SELECT investigation_id, quantity, min_value, max_value, qa_status FROM investigation_conditions"):
        if verified_only and c["qa_status"] != "human_verified":
            continue
        ranges.setdefault(c["investigation_id"], {})[c["quantity"]] = (c["min_value"], c["max_value"])

    cells = {combo: {"labels": dict(zip(dims, combo)), "investigations": [], "n_partial": 0, "n_runs": 0, "n_verified_runs": 0,
                     "run_investigations": set()} for combo in itertools.product(*[axes[d] for d in dims])}
    unmapped_invs = []
    for inv in invs:
        if verified_only and inv["qa_status"] != "human_verified" and "gravity_class" in dims and len(dims) == 1:
            continue
        per_dim, partial_any, missing = [], False, []
        for d in dims:
            labels, partial = _inv_axis_labels(inv, ranges.get(inv["investigation_id"], {}), d)
            if not labels:
                missing.append(d)
            per_dim.append([l for l in labels if l in axes[d]])
            partial_any = partial_any or partial
        if missing:
            unmapped_invs.append({"name": inv["name"], "missing_dims": missing})
            continue
        for combo in itertools.product(*per_dim):
            cell = cells.get(combo)
            if cell is not None:
                cell["investigations"].append(inv["name"])
                cell["n_partial"] += 1 if partial_any else 0

    run_sql = ("SELECT r.run_id, r.gravity_g, r.o2_pct, r.pressure_kpa, r.flow_cm_s, r.qa_status, i.name AS inv "
               "FROM runs r JOIN investigations i ON i.investigation_id=r.investigation_id WHERE r.qa_status <> 'rejected'")
    runs = dbm.q(conn, run_sql)
    unmapped_runs = {"count": 0, "by_missing_dim": {d: 0 for d in dims}}
    for run in runs:
        if verified_only and run["qa_status"] != "human_verified":
            continue
        labels, missing = [], []
        for d in dims:
            lab = gravity_class(run["gravity_g"]) if d == "gravity_class" else _RUN_BIN_FN[d](run[_RUN_FIELD[d]])
            if lab == "unknown" or lab not in axes[d]:
                missing.append(d)
            labels.append(lab)
        if missing:
            unmapped_runs["count"] += 1
            for d in missing:
                unmapped_runs["by_missing_dim"][d] += 1
            continue
        cell = cells[tuple(labels)]
        cell["n_runs"] += 1
        cell["n_verified_runs"] += 1 if run["qa_status"] == "human_verified" else 0
        cell["run_investigations"].add(run["inv"])

    out_cells = []
    for combo, c in cells.items():
        out_cells.append({"labels": c["labels"], "n_investigations": len(set(c["investigations"])), "investigations": sorted(set(c["investigations"])),
                          "n_partial": c["n_partial"], "n_runs": c["n_runs"], "n_verified_runs": c["n_verified_runs"],
                          "run_investigations": sorted(c["run_investigations"]),
                          "is_gap": len(set(c["investigations"])) == 0 and c["n_runs"] == 0})
    return {"dims": list(dims), "axes": axes, "cells": out_cells,
            "unmapped": {"investigations": unmapped_invs, "runs": unmapped_runs},
            "n_investigations_considered": len(invs), "n_runs_considered": len(runs),
            "note": "A gap means no evidence is loaded in this database for that cell, not that NASA has none."}


def gravity_summary(conn) -> dict:
    """How many loaded investigations and runs exist per gravity class (used by the Ask 'Moon/Mars' answer)."""
    out = {c: [] for c in ["micro", "lunar", "mars", "earth", "other", "unknown"]}
    for inv in dbm.q(conn, "SELECT investigation_id, name, gravity_label FROM investigations ORDER BY name"):
        out[gravity_class_from_label(inv["gravity_label"])].append(inv["name"])
    run_counts = {c: 0 for c in out}
    for r in dbm.q(conn, "SELECT gravity_g FROM runs WHERE qa_status <> 'rejected'"):
        run_counts[gravity_class(r["gravity_g"])] += 1
    return {"investigations": out, "runs": run_counts}
