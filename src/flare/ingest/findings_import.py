"""Import curated findings. Every finding's quote MUST appear on the cited page of the cited source (blocks invented findings)."""
from __future__ import annotations
import csv
import re
from pathlib import Path
from ..core import db as dbm

LABELS = {"configuration", "measured_observation", "published_finding", "interpretation", "hypothesis", "unknown"}
REQUIRED = ["statement", "evidence_label", "source_key", "page", "quote"]


def _norm(t: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip() + " "


def import_findings(conn, csv_path: Path) -> dict:
    rep = {"read": 0, "inserted": 0, "skipped_existing": 0, "rejected": []}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        missing = [c for c in REQUIRED if c not in (rd.fieldnames or [])]
        if missing:
            raise ValueError(f"findings CSV is missing columns: {missing}")
        for n, row in enumerate(rd, start=2):
            if not any((v or "").strip() for v in row.values()):
                continue
            rep["read"] += 1
            def reject(why): rep["rejected"].append({"line": n, "reason": why, "statement": (row.get("statement") or "")[:80]})
            if not (row["statement"] or "").strip(): reject("empty statement"); continue
            if row["evidence_label"] not in LABELS: reject(f"evidence_label {row['evidence_label']!r} not in {sorted(LABELS)}"); continue
            src = dbm.q1(conn, "SELECT source_id FROM sources WHERE source_key=?", (row["source_key"],))
            if not src: reject(f"source_key {row['source_key']!r} not found; ingest the paper first"); continue
            try: page = int(row["page"])
            except (TypeError, ValueError): reject("page must be an integer"); continue
            pg = dbm.q1(conn, "SELECT text FROM doc_pages WHERE source_id=? AND page=?", (src["source_id"], page))
            if not pg: reject(f"page {page} has no stored text for this source"); continue
            if _norm(row["quote"]).strip() == "" or _norm(row["quote"]) not in _norm(pg["text"]):
                reject("quote not found on the cited page (whitespace/case-insensitive)"); continue
            inv_id = None
            if (row.get("investigation") or "").strip():
                inv_id = dbm.scalar(conn, "SELECT investigation_id FROM investigations WHERE name=?", (row["investigation"].strip(),))
                if inv_id is None: reject(f"investigation {row['investigation']!r} not found"); continue
            if dbm.q1(conn, "SELECT 1 FROM findings WHERE source_id=? AND page=? AND statement=?", (src["source_id"], page, row["statement"].strip())):
                rep["skipped_existing"] += 1; continue
            conf = (row.get("confidence") or "").strip().lower() or None
            conn.execute("""INSERT INTO findings(investigation_id,statement,evidence_label,topic,quote,limitations,confidence,source_id,source_ref,page,qa_status)
                            VALUES (?,?,?,?,?,?,?,?,?,?, 'unverified')""",
                         (inv_id, row["statement"].strip(), row["evidence_label"], (row.get("topic") or "").strip() or None, row["quote"].strip(),
                          (row.get("limitations") or "").strip() or None, conf if conf in ("low", "medium", "high") else None,
                          src["source_id"], f"page {page}", page))
            rep["inserted"] += 1
    conn.commit()
    return rep
