"""Thin FastAPI wrapper (P1). No business logic here: every endpoint calls one core function.
NOTE: written to spec but NOT executed in the build sandbox (fastapi is not installed there). Run: uvicorn flare.api.main:app --app-dir src
"""
from __future__ import annotations
from fastapi import FastAPI, HTTPException
from ..core import compare, coverage, db as dbm, explore, ranking
from ..core.ask import ask as ask_question
from ..core.bins import AXES

app = FastAPI(title="FLARE API", version="1.0")


def _conn():
    return dbm.connect(check_same_thread=False)


@app.get("/api/v1/health")
def health():
    c = _conn()
    return {"fts5": dbm.check_fts5(c), "stats": dbm.stats(c)}


@app.get("/api/v1/investigations")
def investigations(regime: str | None = None, fuel_type: str | None = None, gravity_class: str | None = None, q: str | None = None):
    return explore.list_investigations(_conn(), regime=regime, fuel_type=fuel_type, gravity_class=gravity_class, text=q)


@app.get("/api/v1/investigations/{name}")
def investigation(name: str):
    p = explore.get_profile(_conn(), name)
    if not p:
        raise HTTPException(404, "investigation not found")
    return p


@app.get("/api/v1/runs")
def runs(investigation: str | None = None, limit: int = 200, offset: int = 0):
    return explore.search_runs(_conn(), investigation=investigation, limit=limit, offset=offset)


@app.get("/api/v1/coverage")
def coverage_map(dims: str = "gravity_class,o2_bin", verified_only: bool = False):
    chosen = tuple(d for d in dims.split(",") if d)
    if not chosen or any(d not in AXES for d in chosen):
        raise HTTPException(400, f"dims must come from {list(AXES)}")
    return coverage.coverage(_conn(), chosen, verified_only=verified_only)


@app.post("/api/v1/compare")
def compare_items(body: dict):
    if "run_ids" in body:
        return compare.compare_runs(_conn(), body["run_ids"])
    if "investigations" in body:
        return compare.compare_investigations(_conn(), body["investigations"])
    raise HTTPException(400, "send run_ids or investigations")


@app.get("/api/v1/rankings")
def rankings(gravity_class: str | None = None):
    return ranking.rank_investigations(_conn(), {"gravity_class": gravity_class} if gravity_class else {})


@app.post("/api/v1/ask")
def ask_endpoint(body: dict):
    return ask_question(_conn(), body.get("question", ""), investigation_ids=body.get("investigation_ids"))
