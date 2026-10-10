"""SQLite helper. foreign_keys=ON on EVERY connection (never call sqlite3.connect directly)."""
import sqlite3
from pathlib import Path
from .config import settings

SCHEMA = Path(__file__).parent / "schema.sql"

def get_conn(db_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or settings.DB_PATH, timeout=15)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn

def init_schema(db_path: str | None = None) -> None:
    conn = get_conn(db_path)
    try:
        conn.executescript(SCHEMA.read_text())
        conn.commit()
    finally:
        conn.close()
