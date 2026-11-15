"""Condition bins. The SQL view v_run_bins in db/schema.sql must agree with these (tests/test_bins.py checks it)."""
from __future__ import annotations
import math

GRAVITY_LABELS = ["micro", "lunar", "mars", "earth"]
# label -> (low, high) half-open [low, high); inf for open ends
O2_BINS = {"lt21": (-math.inf, 21), "21-25": (21, 25), "25-30": (25, 30), "30-40": (30, 40), "gte40": (40, math.inf)}
PRESSURE_BINS = {"lt60": (-math.inf, 60), "60-95": (60, 95), "95-110": (95, 110), "gte110": (110, math.inf)}
FLOW_BINS = {"quiescent": (0, 0), "0-10": (0, 10), "10-30": (10, 30), "gte30": (30, math.inf)}

AXES = {
    "gravity_class": GRAVITY_LABELS,
    "o2_bin": list(O2_BINS),
    "pressure_bin": list(PRESSURE_BINS),
    "flow_bin": list(FLOW_BINS),
}
AXIS_TITLES = {"gravity_class": "Gravity", "o2_bin": "Oxygen (% by volume)", "pressure_bin": "Pressure (kPa)", "flow_bin": "Airflow (cm/s)"}
AXIS_QUANTITY = {"o2_bin": "o2_pct", "pressure_bin": "pressure_kpa", "flow_bin": "flow_cm_s"}


def gravity_class(g: float | None) -> str:
    if g is None:
        return "unknown"
    if g < 0.01:
        return "micro"
    if 0.10 <= g <= 0.25:
        return "lunar"
    if 0.30 <= g <= 0.45:
        return "mars"
    if g >= 0.9:
        return "earth"
    return "other"


def gravity_class_from_label(label: str | None) -> str:
    """Map a written label such as 'microgravity' to a class. Unrecognized text -> 'unknown' (never guessed)."""
    t = (label or "").strip().lower()
    if t in ("microgravity", "micro-gravity", "micro"):
        return "micro"
    if t in ("lunar", "lunar gravity", "moon"):
        return "lunar"
    if t in ("mars", "martian", "mars gravity"):
        return "mars"
    if t in ("earth", "1g", "normal gravity", "1 g"):
        return "earth"
    return "unknown"


def _bin(value: float | None, bins: dict) -> str:
    if value is None:
        return "unknown"
    for label, (lo, hi) in bins.items():
        if lo <= value < hi:
            return label
    return "unknown"


def o2_bin(x): return _bin(x, O2_BINS)
def pressure_bin(x): return _bin(x, PRESSURE_BINS)


def flow_bin(x: float | None) -> str:
    if x is None:
        return "unknown"
    if x == 0:
        return "quiescent"
    return _bin(x, {k: v for k, v in FLOW_BINS.items() if k != "quiescent"})


def bins_overlapping(lo: float | None, hi: float | None, bins: dict) -> list[str]:
    """Bins touched by a declared range. If only one end is known, only that point is used (see coverage.py)."""
    pts = [p for p in (lo, hi) if p is not None]
    if not pts:
        return []
    a, b = min(pts), max(pts)
    out = []
    for label, (blo, bhi) in bins.items():
        if label == "quiescent":
            if a <= 0 <= b:
                out.append(label)
        elif a < bhi and b >= blo:
            out.append(label)
    return out
