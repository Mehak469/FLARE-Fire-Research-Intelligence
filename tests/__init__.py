import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("DB_PATH", str(Path(tempfile.gettempdir()) / "flare_test_default.db"))
os.environ.setdefault("LLM_PROVIDER", "offline")
