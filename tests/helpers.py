"""Shared test helpers. Tests run against REAL data files (investigations.json, the BASS-II sample), never invented values."""
import tempfile
import uuid
from pathlib import Path
from flare import config
from flare.core import db as dbm
from flare.ingest.investigations import ingest_investigations
from flare.ingest.table_loader import load_table
from flare.ingest.verify import validate

ROOT = config.ROOT


def fresh_db(with_runs: bool = True, with_validate: bool = False):
    path = Path(tempfile.gettempdir()) / f"flare_test_{uuid.uuid4().hex}.db"
    conn = dbm.init_db(path, overwrite=True)
    ingest_investigations(conn)
    if with_runs:
        load_table(conn, ROOT / "config" / "mappings" / "bass2.yaml", ROOT / "data" / "staging" / "bass2_staging_sample.csv")
    if with_validate:
        validate(conn)
    return conn, path


def run_id(conn, inv: str, label: str) -> int:
    return dbm.scalar(conn, "SELECT r.run_id FROM runs r JOIN investigations i USING(investigation_id) WHERE i.name=? AND r.run_label=?", (inv, label))
