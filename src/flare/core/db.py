"""Database access. All SQL in the app goes through parameterized calls (Rule R5)."""
from __future__ import annotations
import sqlite3
from pathlib import Path
from .. import config


def connect(path: str | Path | None = None, check_same_thread: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or config.DB_PATH), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def check_fts5(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp._fts_probe USING fts5(x)")
        conn.execute("DROP TABLE temp._fts_probe")
        return True
    except sqlite3.OperationalError:
        return False


def init_db(path: str | Path | None = None, schema_path: str | Path | None = None, overwrite: bool = False) -> sqlite3.Connection:
    """Create the database from schema.sql. Refuses to overwrite an existing file unless overwrite=True."""
    target = Path(path or config.DB_PATH)
    if target.exists():
        if not overwrite:
            raise FileExistsError(f"{target} exists; pass overwrite=True to recreate it")
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(target)
    if not check_fts5(conn):
        raise RuntimeError("This SQLite build has no FTS5 support. Install a Python with FTS5.")
    conn.executescript(Path(schema_path or config.SCHEMA_PATH).read_text(encoding="utf-8"))
    conn.commit()
    return conn


def q(conn: sqlite3.Connection, sql: str, params: tuple | list = ()) -> list[dict]:
    """Run a parameterized SELECT and return a list of dicts."""
    return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def q1(conn: sqlite3.Connection, sql: str, params: tuple | list = ()) -> dict | None:
    rows = q(conn, sql, params)
    return rows[0] if rows else None


def scalar(conn: sqlite3.Connection, sql: str, params: tuple | list = ()):
    row = conn.execute(sql, tuple(params)).fetchone()
    return row[0] if row else None


def add_flag(conn, table: str, row_id: int, flag: str, detail: str = "", severity: str = "warn", created_by: str = "ingest"):
    exists = conn.execute(
        "SELECT 1 FROM data_flags WHERE table_name=? AND row_id=? AND flag=? AND COALESCE(detail,'')=? AND resolved=0",
        (table, row_id, flag, detail or ""),
    ).fetchone()
    if exists:
        return  # idempotent: re-running ingestion does not duplicate flags
    conn.execute(
        "INSERT INTO data_flags(table_name,row_id,flag,detail,severity,created_by) VALUES (?,?,?,?,?,?)",
        (table, row_id, flag, detail, severity, created_by),
    )


def stats(conn: sqlite3.Connection) -> dict:
    """Live headline counts for the UI footer and home page. Never hardcoded (Rule R8)."""
    return {
        "investigations": scalar(conn, "SELECT COUNT(*) FROM investigations"),
        "runs": scalar(conn, "SELECT COUNT(*) FROM runs WHERE qa_status <> 'rejected'"),
        "verified_runs": scalar(conn, "SELECT COUNT(*) FROM runs WHERE qa_status = 'human_verified'"),
        "outcome_measurements": scalar(conn, "SELECT COUNT(*) FROM measurements m JOIN metrics x ON x.metric_id=m.metric_id WHERE x.is_outcome=1"),
        "measurements": scalar(conn, "SELECT COUNT(*) FROM measurements"),
        "findings": scalar(conn, "SELECT COUNT(*) FROM findings WHERE qa_status <> 'rejected'"),
        "verified_findings": scalar(conn, "SELECT COUNT(*) FROM findings WHERE qa_status = 'human_verified'"),
        "sources": scalar(conn, "SELECT COUNT(*) FROM sources"),
        "paper_pages": scalar(conn, "SELECT COUNT(*) FROM doc_pages dp JOIN sources s ON s.source_id=dp.source_id WHERE s.source_type IN ('ntrs_report','journal_paper')"),
        "open_flags": scalar(conn, "SELECT COUNT(*) FROM data_flags WHERE resolved=0"),
    }
