"""Parsing helpers for messy source text. Anything inferred is reported in `flags`."""
from __future__ import annotations
import datetime as dt
import re

MATERIAL_WORDS = {"pmma": "PMMA", "nomex": "Nomex", "sibal": "SIBAL", "ultem": "Ultem", "silicone": "Silicone"}


def parse_number(x) -> float | None:
    """One clean number, else None. Blank stays None, never 0."""
    try:
        s = str(x).strip()
        return float(s) if s != "" else None
    except (ValueError, TypeError):
        return None


def parse_date_mdy(text: str) -> dt.date:
    return dt.datetime.strptime(str(text).strip(), "%m/%d/%Y").date()


def day_of_year(d: dt.date) -> int:
    return d.timetuple().tm_yday


def parse_fuel_text(text: str, default_material: str | None = None) -> dict:
    """'100 micron PMMA film 2 cm wide' / '2 cm 0.1 mm PMMA film' -> material, thickness_mm, width_mm, flags.

    Never guesses silently: a missing material word is flagged, a default is applied only if the mapping allows it.
    """
    t = (text or "").lower()
    out = {"material": None, "thickness_mm": None, "width_mm": None, "flags": []}
    m = re.search(r"(\d+(?:\.\d+)?)\s*(micron|microns|um|mm)\b", t)
    if m:
        v = float(m.group(1))
        out["thickness_mm"] = v / 1000.0 if m.group(2) in ("micron", "microns", "um") else v
    else:
        out["flags"].append("thickness_not_parsed")
    w = re.search(r"(\d+(?:\.\d+)?)\s*cm\b", t)
    if w:
        out["width_mm"] = float(w.group(1)) * 10.0
    else:
        out["flags"].append("width_not_parsed")
    for word, canon in MATERIAL_WORDS.items():
        if word in t:
            out["material"] = canon
            break
    else:
        if default_material:
            out["material"] = default_material
            out["flags"].append("material_inferred")
        else:
            out["flags"].append("material_not_found")
    return out
