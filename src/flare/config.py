"""Paths and configuration loading. Nothing here touches the database."""
from __future__ import annotations
import os
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("DB_PATH", ROOT / "db" / "flame.db"))
SCHEMA_PATH = ROOT / "db" / "schema.sql"
CONFIG_DIR = ROOT / "config"


def load_yaml(name: str) -> dict:
    """Load config/<name> (e.g. 'ranking.yaml')."""
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
