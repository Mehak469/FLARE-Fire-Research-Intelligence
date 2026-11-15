"""Human verification helpers and the automatic validator. Only a person can set human_verified."""
from __future__ import annotations
import json
from ..core import db as dbm


def validate(conn) -> dict:
    """Scripted checks. Runs with no unresolved flags become auto_checked. Nothing is ever set to human_verified here."""
    rep = {"checks": [], "auto_checked": 0}
    def check(name, ok, detail=""):
        rep["checks"].append({"check": name, "ok": bool(ok), "detail": detail})
    n_fts = dbm.scalar(conn, "SELECT COUNT(*) FROM doc_chunks_fts")
    n_chunks = dbm.scalar(conn, "SELECT COUNT(*) FROM doc_chunks")
    check("search index matches chunk count", n_fts == n_chunks, f"{n_fts} indexed / {n_chunks} chunks")
    check("every run has a source", dbm.scalar(conn, "SELECT COUNT(*) FROM runs WHERE source_id IS NULL") == 0)
    check("every run has a sample", dbm.scalar(conn, "SELECT COUNT(*) FROM runs r WHERE NOT EXISTS (SELECT 1 FROM samples s WHERE s.run_id=r.run_id)") == 0,
          "runs without a sample are flagged sample_not_stored")
    check("every finding has a page and source", dbm.scalar(conn, "SELECT COUNT(*) FROM findings WHERE source_ref IS NULL OR source_id IS NULL") == 0)
    check("measurements have raw values", dbm.scalar(conn, "SELECT COUNT(*) FROM measurements WHERE value_raw IS NULL") == 0)
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    check("foreign keys consistent", not fk, f"{len(fk)} violations")
    cur = conn.execute("""UPDATE runs SET qa_status='auto_checked' WHERE qa_status='unverified' AND source_id IS NOT NULL
                          AND NOT EXISTS (SELECT 1 FROM data_flags f WHERE f.table_name='runs' AND f.row_id=runs.run_id AND f.resolved=0 AND f.severity IN ('warn','error'))""")
    rep["auto_checked"] = cur.rowcount
    conn.commit()
    return rep


def verify_runs(conn, investigation: str, labels: list[str], by: str, accept_flags: bool = False, apply: bool = False) -> list[dict]:
    """Show stored vs original row; set human_verified only when apply=True. Unresolved flags block unless accept_flags=True."""
    out = []
    for lab in labels:
        r = dbm.q1(conn, "SELECT r.*, i.name AS inv FROM runs r JOIN investigations i ON i.investigation_id=r.investigation_id WHERE i.name=? AND r.run_label=?", (investigation, lab))
        if not r:
            out.append({"run": lab, "status": "not found"}); continue
        flags = dbm.q(conn, "SELECT flag_id, flag, detail FROM data_flags WHERE table_name='runs' AND row_id=? AND resolved=0", (r["run_id"],))
        entry = {"run": lab, "stored": {k: r[k] for k in ("run_date", "gravity_g", "o2_pct", "pressure_kpa", "flow_cm_s")},
                 "original_row": json.loads(r["raw_record"] or "{}"), "open_flags": flags, "status": "shown"}
        if apply:
            if flags and not accept_flags:
                entry["status"] = "blocked: open flags (re-run with accept_flags after checking them against the source)"
            else:
                conn.execute("UPDATE runs SET qa_status='human_verified' WHERE run_id=?", (r["run_id"],))
                conn.execute("UPDATE measurements SET qa_status='human_verified' WHERE run_id=?", (r["run_id"],))
                for f in flags:
                    conn.execute("UPDATE data_flags SET resolved=1 WHERE flag_id=?", (f["flag_id"],))
                conn.execute("INSERT INTO edit_log(table_name,row_id,field,old_value,new_value,actor,reason) VALUES ('runs',?,'qa_status',?,?,?,?)",
                             (r["run_id"], r["qa_status"], "human_verified", by, "verified against source" + ("; flags accepted" if flags else "")))
                entry["status"] = "human_verified"
        out.append(entry)
    conn.commit()
    return out


def verify_investigation_record(conn, name: str, by: str) -> bool:
    """Mark an investigation record and its declared ranges as human-verified after checking its PSI page."""
    inv = dbm.q1(conn, "SELECT investigation_id, qa_status FROM investigations WHERE name=?", (name,))
    if not inv:
        return False
    conn.execute("UPDATE investigations SET qa_status='human_verified' WHERE investigation_id=?", (inv["investigation_id"],))
    conn.execute("UPDATE investigation_conditions SET qa_status='human_verified' WHERE investigation_id=?", (inv["investigation_id"],))
    conn.execute("INSERT INTO edit_log(table_name,row_id,field,old_value,new_value,actor,reason) VALUES ('investigations',?,'qa_status',?,?,?,?)",
                 (inv["investigation_id"], inv["qa_status"], "human_verified", by, "record and ranges checked against the PSI page"))
    conn.commit()
    return True
