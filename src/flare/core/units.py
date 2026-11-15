"""Unit conversion. Unknown units never guess: they return (None, reason)."""
from __future__ import annotations

# quantity -> canonical unit
CANONICAL = {"pressure": "kPa", "speed": "cm/s", "length": "mm", "spread_rate": "mm/s",
             "temperature": "K", "gravity": "g", "oxygen": "pct"}

# multiplicative factors to the canonical unit; keys are lowercase, whitespace removed
_FACTORS = {
    "pressure": {"kpa": 1.0, "pa": 0.001, "psi": 6.89476, "atm": 101.325, "bar": 100.0, "torr": 0.133322, "mmhg": 0.133322},
    "speed": {"cm/s": 1.0, "m/s": 100.0, "mm/s": 0.1, "in/s": 2.54},
    "length": {"mm": 1.0, "cm": 10.0, "m": 1000.0, "micron": 0.001, "microns": 0.001, "um": 0.001, "in": 25.4, "inch": 25.4},
    "spread_rate": {"mm/s": 1.0, "cm/s": 10.0, "m/s": 1000.0, "in/s": 25.4},
    "gravity": {"g": 1.0, "m/s2": 1 / 9.80665, "m/s^2": 1 / 9.80665},
}


def _norm(unit: str) -> str:
    return unit.strip().lower().replace(" ", "").replace("\u00b2", "2")


def convert(value: float | None, unit: str | None, quantity: str) -> tuple[float | None, str | None]:
    """Return (converted_value, flag). flag is None when the conversion is certain."""
    if value is None:
        return None, None
    if unit is None or unit.strip() == "":
        return None, f"no unit given for {quantity}"
    u = _norm(unit)
    if quantity == "temperature":
        if u in ("k", "kelvin"):
            return float(value), None
        if u in ("c", "degc", "\u00b0c", "celsius"):
            return float(value) + 273.15, None
        if u in ("f", "degf", "\u00b0f", "fahrenheit"):
            return (float(value) - 32.0) * 5.0 / 9.0 + 273.15, None
        return None, f"unknown temperature unit {unit!r}"
    if quantity == "oxygen":
        if u in ("pct", "%", "percent", "vol%"):
            return float(value), None
        if u in ("fraction", "molefraction", "mole_fraction"):
            return float(value) * 100.0, None
        return None, f"unknown oxygen unit {unit!r}"
    table = _FACTORS.get(quantity)
    if table is None:
        return None, f"unknown quantity {quantity!r}"
    if u not in table:
        return None, f"unknown {quantity} unit {unit!r}"
    return float(value) * table[u], None


def o2_pct_from_partial_pressure(p_o2: float | None, p_total: float | None) -> tuple[float | None, str | None]:
    """Oxygen percent from partial pressure; only possible when the total pressure is stated."""
    if p_o2 is None or p_total is None:
        return None, "total pressure not stated; cannot convert partial pressure to percent"
    if p_total <= 0:
        return None, "total pressure must be positive"
    return 100.0 * p_o2 / p_total, None
