"""Load the investigation-level records (investigations.json, cross-checked with investigations.csv).

PROVENANCE NOTE: this file was compiled by a third party from NASA PSI records. We store every value
as 'unverified' and keep each investigation's PSI page and DOI so a person can verify it at the source.
"""
from __future__ import annotations
import csv
import hashlib
import json
import re
from pathlib import Path
from .. import config
from ..core import db as dbm
from ..core.bins import gravity_class_from_label

TEXT_SECTIONS = [  # (field, heading)
    ("objective", "Objective"), ("variables", "Variables studied"), ("fuel_detail", "Fuels and samples"),
    ("hardware", "Hardware"), ("sensors", "Sensors"), ("relevance_note", "Relevance note"),
    ("earth_application", "Earth application"),
]
RANGE_FIELDS = [("o2_pct", "o2_min_pct", "o2_max_pct", "pct"), ("pressure_kpa", "pressure_kpa_min", "pressure_kpa_max", "kPa"),
                ("flow_cm_s", "flow_min_cm_s", "flow_max_cm_s", "cm/s")]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _join(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, list):
        return "; ".join(str(x) for x in v) if v else None
    return str(v)


def _split_urls(urls) -> tuple[str | None, str | None]:
    """Return (psi_page_url, doi) from the source_url list."""
    urls = urls if isinstance(urls, list) else ([urls] if urls else [])
    psi = next((u for u in urls if "psi.nasa.gov" in u), None)
    doi = next((u for u in urls if "doi.org/" in u), None)
    return psi, (doi.split("doi.org/")[-1] if doi else None)


def ingest_investigations(conn, json_path: Path | None = None, csv_path: Path | None = None, retrieved_on: str = "2026-11-14") -> dict:
    json_path = Path(json_path or config.ROOT / "data" / "raw" / "investigations.json")
    csv_path = Path(csv_path or config.ROOT / "data" / "raw" / "investigations.csv")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    items = data["items"]
    report = {"loaded": 0, "conditions": 0, "chunks": 0, "warnings": []}

    # cross-check the CSV against the JSON (same ids)
    if csv_path.exists():
        with open(csv_path, encoding="utf-8") as fh:
            csv_ids = {r["id"] for r in csv.DictReader(fh)}
        json_ids = {i["id"] for i in items}
        if csv_ids != json_ids:
            report["warnings"].append(f"CSV and JSON differ: only in CSV {sorted(csv_ids - json_ids)}, only in JSON {sorted(json_ids - csv_ids)}")

    regime_map = config.load_yaml("regime_map.yaml")
    regimes = {r["code"]: r["regime_id"] for r in dbm.q(conn, "SELECT regime_id, code FROM regimes")}

    # one source row for the compiled file itself (lineage)
    conn.execute("""INSERT OR IGNORE INTO sources(source_key,source_type,title,citation,local_file,sha256,retrieved_on)
                    VALUES ('investigations-json','other','investigations.json (third-party compilation of PSI investigation records)',
                    'Compiled by a third party from NASA PSI; values unverified', ?, ?, ?)""",
                 (str(json_path.relative_to(config.ROOT)) if json_path.is_relative_to(config.ROOT) else str(json_path), sha256(json_path), retrieved_on))
    file_source_id = dbm.scalar(conn, "SELECT source_id FROM sources WHERE source_key='investigations-json'")

    for it in items:
        code = it["id"]
        psi_url, doi = _split_urls(it.get("source_url"))
        psi_id = (re.search(r"(PSI-\d+)", psi_url or "") or [None, None])[1]
        regime = regime_map.get(code)
        if regime is None:
            report["warnings"].append(f"{code}: no regime in config/regime_map.yaml; stored as 'other'")
            regime = "other"
        conn.execute("""INSERT INTO investigations(name,full_name,psi_id,doi,program,platform,regime_id,summary,psi_url,safety_area,fuel_type,
                        fuel_detail,hardware,sensors,objective,variables,habitats,earth_application,relevance_note,gravity_label,third_party_status)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(name) DO UPDATE SET full_name=excluded.full_name, psi_id=excluded.psi_id, doi=excluded.doi,
                          program=excluded.program, regime_id=excluded.regime_id, psi_url=excluded.psi_url, safety_area=excluded.safety_area,
                          fuel_type=excluded.fuel_type, fuel_detail=excluded.fuel_detail, hardware=excluded.hardware, sensors=excluded.sensors,
                          objective=excluded.objective, variables=excluded.variables, habitats=excluded.habitats,
                          earth_application=excluded.earth_application, relevance_note=excluded.relevance_note,
                          gravity_label=excluded.gravity_label, third_party_status=excluded.third_party_status""",
                     (code, it.get("name"), psi_id, doi, it.get("project") or None, None, regimes[regime], it.get("objective"), psi_url,
                      _join(it.get("safety_area")), _join(it.get("fuel_type")), it.get("fuel_detail"), _join(it.get("hardware")),
                      _join(it.get("sensors")), it.get("objective"), it.get("variables"), _join(it.get("habitats")),
                      it.get("earth_application"), it.get("relevance_note"), _join(it.get("gravity")), it.get("data_status")))
        inv_id = dbm.scalar(conn, "SELECT investigation_id FROM investigations WHERE name=?", (code,))

        # the PSI record page is the citation target for this investigation's text and ranges
        key = code.lower()
        conn.execute("""INSERT OR IGNORE INTO sources(source_key,source_type,title,url,doi,retrieved_on)
                        VALUES (?, 'psi_file', ?, ?, ?, ?)""", (f"{key}-record", f"PSI record: {it.get('name')}", psi_url, doi, retrieved_on))
        src_id = dbm.scalar(conn, "SELECT source_id FROM sources WHERE source_key=?", (f"{key}-record",))
        conn.execute("INSERT OR IGNORE INTO investigation_sources(investigation_id,source_id) VALUES (?,?)", (inv_id, src_id))
        conn.execute("INSERT OR IGNORE INTO investigation_sources(investigation_id,source_id) VALUES (?,?)", (inv_id, file_source_id))

        # declared ranges (blank in the source stays missing; a one-ended range keeps the other end NULL)
        for qty, lo_k, hi_k, unit in RANGE_FIELDS:
            lo, hi = it.get(lo_k), it.get(hi_k)
            if lo is None and hi is None:
                continue
            conn.execute("""INSERT INTO investigation_conditions(investigation_id,quantity,min_value,max_value,unit,source_id,source_ref)
                            VALUES (?,?,?,?,?,?,?)
                            ON CONFLICT(investigation_id,quantity) DO UPDATE SET min_value=excluded.min_value, max_value=excluded.max_value""",
                         (inv_id, qty, lo, hi, unit, file_source_id, f"investigations.json item {code}"))
            report["conditions"] += 1
            if lo is None or hi is None:
                dbm.add_flag(conn, "investigations", inv_id, "one_ended_range", f"{qty}: only one end stated (min={lo}, max={hi})", "info")

        # searchable text: one chunk per section, all on virtual page 1 of the record source
        conn.execute("DELETE FROM doc_chunks WHERE investigation_id=?", (inv_id,))
        conn.execute("DELETE FROM doc_pages WHERE source_id=?", (src_id,))
        page_parts, idx = [], 0
        for field, heading in TEXT_SECTIONS:
            txt = _join(it.get(field))
            if not txt:
                continue
            chunk = f"[{code} / {it.get('name')} - {heading}] {txt}"
            conn.execute("INSERT INTO doc_chunks(source_id,investigation_id,section,page,chunk_index,text) VALUES (?,?,?,?,?,?)",
                         (src_id, inv_id, field, 1, idx, chunk))
            page_parts.append(chunk); idx += 1; report["chunks"] += 1
        conn.execute("INSERT OR REPLACE INTO doc_pages(source_id,page,text) VALUES (?,?,?)", (src_id, 1, "\n".join(page_parts)))

        if gravity_class_from_label(_join(it.get("gravity"))) == "unknown":
            report["warnings"].append(f"{code}: gravity label {it.get('gravity')!r} not recognized")
        report["loaded"] += 1
    conn.commit()
    return report
