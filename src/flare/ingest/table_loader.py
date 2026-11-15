"""Mapping-driven loader for PSI experimental tables (CSV or Excel). Adding an investigation = adding a YAML file.

Behavior (spec section 5.4): idempotent, parents first, one transaction, blanks stay missing, qualifiers kept,
odd values flagged not fixed, raw row kept as JSON on every run.
"""
from __future__ import annotations
import csv
import hashlib
import json
import re
from pathlib import Path
import yaml
from .. import config
from ..core import db as dbm
from ..core.normalize import parse_date_mdy, parse_fuel_text, parse_number, day_of_year


def _key(h: str) -> str:
    return re.sub(r"\s+", " ", h.strip().lower())


def read_rows(path: Path) -> tuple[list[str], list[dict]]:
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        import pandas as pd
        df = pd.read_excel(path, dtype=str).fillna("")
        return list(df.columns), df.to_dict("records")
    with open(path, newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        return list(rd.fieldnames or []), [dict(r) for r in rd]


class Columns:
    """Case/whitespace-insensitive header lookup that reports what is missing instead of guessing."""
    def __init__(self, headers: list[str]):
        self.headers = headers
        self._by_key = {_key(h): h for h in headers}

    def get(self, row: dict, name: str) -> str:
        real = self._by_key.get(_key(name))
        return (row.get(real, "") if real is not None else "").strip()

    def has(self, name: str) -> bool:
        return _key(name) in self._by_key


def load_table(conn, mapping_path: Path, data_path: Path, retrieved_on: str = "2026-11-14") -> dict:
    m = yaml.safe_load(Path(mapping_path).read_text(encoding="utf-8"))
    headers, rows = read_rows(data_path)
    cols = Columns(headers)
    report = {"rows_in_file": len(rows), "loaded": 0, "skipped_existing": 0, "flags": [], "missing_columns": []}

    needed = [m["run_label"], m["run_date"]["col"], m["conditions"]["o2_pct"]["col"], m["sample"]["fuel_col"]]
    needed += list(m.get("attributes", {}).values()) + [x["col"] for x in m.get("measurements", [])]
    report["missing_columns"] = [n for n in needed if not cols.has(n)]
    if cols.has(m["run_label"]) is False or cols.has(m["run_date"]["col"]) is False:
        raise ValueError(f"Required columns missing: {report['missing_columns']}. Found headers: {headers}")

    inv = dbm.q1(conn, "SELECT investigation_id FROM investigations WHERE name=?", (m["investigation"],))
    if inv is None:
        raise ValueError(f"Investigation {m['investigation']!r} not found. Run ingest-investigations first.")
    inv_id = inv["investigation_id"]

    s = m["source"]
    data_path = Path(data_path)
    conn.execute("""INSERT INTO sources(source_key,source_type,title,url,doi,local_file,sha256,retrieved_on)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(source_key) DO UPDATE SET sha256=excluded.sha256, local_file=excluded.local_file, retrieved_on=excluded.retrieved_on""",
                 (s["source_key"], s["type"], s["title"], s.get("url"), s.get("doi"), str(data_path),
                  hashlib.sha256(data_path.read_bytes()).hexdigest(), retrieved_on))
    src_id = dbm.scalar(conn, "SELECT source_id FROM sources WHERE source_key=?", (s["source_key"],))
    conn.execute("INSERT OR IGNORE INTO investigation_sources(investigation_id,source_id) VALUES (?,?)", (inv_id, src_id))

    mat_name = m["sample"].get("default_material")
    if mat_name:
        conn.execute("INSERT OR IGNORE INTO materials(canonical_name,category) VALUES (?, 'polymer')", (mat_name,))
    metric_ids = {r["code"]: r["metric_id"] for r in dbm.q(conn, "SELECT metric_id, code FROM metrics")}
    gravity = m.get("constants", {}).get("gravity_g", {}).get("value")
    gravity_note = m.get("constants", {}).get("gravity_g", {}).get("note", "")

    try:
        for row in rows:
            label = cols.get(row, m["run_label"])
            if not label:
                continue
            if dbm.q1(conn, "SELECT 1 FROM runs WHERE investigation_id=? AND run_label=?", (inv_id, label)):
                report["skipped_existing"] += 1
                continue
            ref = f"{s['title']}, test {label}"
            flags: list[tuple[str, str, str]] = []  # (flag, detail, severity)

            # date + cross-check against a day-of-year column if present
            d = None
            raw_date = cols.get(row, m["run_date"]["col"])
            try:
                d = parse_date_mdy(raw_date)
            except ValueError:
                flags.append(("date_unparsed", f"{raw_date!r}", "warn"))
            gmt = parse_number(cols.get(row, m.get("attributes", {}).get("gmt_day_of_year", "")))
            if d and gmt is not None and int(gmt) != day_of_year(d):
                flags.append(("date_vs_day_of_year", f"GMT {int(gmt)} != day-of-year {day_of_year(d)} of {d}", "warn"))

            o2i = parse_number(cols.get(row, m["conditions"]["o2_pct"]["col"]))
            if o2i is None:
                flags.append(("o2_initial_missing", "initial oxygen blank in source", "warn"))

            cur = conn.execute(
                """INSERT INTO runs(investigation_id,run_label,run_date,gravity_g,o2_pct,pressure_kpa,flow_cm_s,flow_mode,
                   source_id,source_ref,raw_record,qa_status,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,'unverified',?)""",
                (inv_id, label, d.isoformat() if d else None, gravity, o2i, None, None, "unknown", src_id, ref,
                 json.dumps(row), f"gravity_g from investigation record: {gravity_note}; pressure and flow velocity not in this table"))
            run_id = cur.lastrowid

            fuel_text = cols.get(row, m["sample"]["fuel_col"])
            fu = parse_fuel_text(fuel_text, default_material=mat_name)
            for fl in fu["flags"]:
                sev = "warn"
                detail = {"material_inferred": f"material word absent in {fuel_text!r}; {mat_name} assumed from the series (verify in Read Me)"}.get(fl, f"{fl}: {fuel_text!r}")
                flags.append((fl, detail, sev))
            mat_id = dbm.scalar(conn, "SELECT material_id FROM materials WHERE canonical_name=?", (fu["material"],)) if fu["material"] else None
            if mat_id is not None:
                conn.execute("INSERT INTO samples(run_id,material_id,geometry,thickness_mm,width_mm,notes) VALUES (?,?,?,?,?,?)",
                             (run_id, mat_id, m["sample"].get("geometry"), fu["thickness_mm"], fu["width_mm"], f"source text: {fuel_text!r}"))
            else:
                flags.append(("sample_not_stored", f"no material for {fuel_text!r}", "error"))

            for key, col in m.get("attributes", {}).items():
                v = cols.get(row, col)
                if v != "":
                    conn.execute("INSERT INTO run_attributes(run_id,key,value_text,value_num,source_ref) VALUES (?,?,?,?,?)",
                                 (run_id, key, v, parse_number(v), ref))

            for ms in m.get("measurements", []):
                raw = cols.get(row, ms["col"])
                if raw == "":
                    flags.append(("blank_measurement", f"{ms['metric']} blank in source (stored as missing)", "info"))
                    continue
                val = parse_number(raw)
                if val is None:
                    flags.append(("non_numeric_measurement", f"{ms['metric']}={raw!r} kept only as text", "warn"))
                    continue
                conn.execute("""INSERT INTO measurements(run_id,metric_id,value_si,value_raw,unit_raw,source_id,source_ref,extracted_by)
                                VALUES (?,?,?,?,?,?,?, 'script')""", (run_id, metric_ids[ms["metric"]], val, raw, ms["unit"], src_id, ref))
                if ms["metric"].startswith(("co_", "co2_")) and val < 0:
                    flags.append(("negative_gas", f"{ms['metric']}={raw} (kept as written; likely sensor offset, do not clip)", "warn"))
                if ms["metric"] == "o2_final_pct" and o2i is not None and abs(val - o2i) > 3:
                    flags.append(("o2_large_change", f"final O2 {raw}% vs initial {o2i}% (failed test or data error? check)", "warn"))

            for fl, detail, sev in flags:
                dbm.add_flag(conn, "runs", run_id, fl, detail, sev)
                report["flags"].append(f"{label}: {fl} - {detail}")
            report["loaded"] += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return report
