#!/usr/bin/env python3
"""Annex C CSV loader - upsert, tolerant, accepts judges' reserved IDs. Order:
products -> customers -> orders -> order_items -> returns (FK-safe)."""
import argparse, csv, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import get_conn, init_schema

TABLES = ("products", "customers", "orders", "order_items", "returns")

def upsert_rows(conn, table: str, rows: list[dict]) -> int:
    n = 0
    for r in rows:
        cols = list(r.keys())
        conn.execute(f"INSERT OR REPLACE INTO {table}({','.join(cols)}) "
                     f"VALUES ({','.join('?' * len(cols))})",
                     [("" if r[c] in (None,) else r[c]) for c in cols])
        n += 1
    return n

def load_dir(db_path: str, dirpath: str) -> None:
    d = Path(dirpath)
    conn = get_conn(db_path)
    try:
        init_schema(db_path)
        total = {}
        for t in TABLES:
            f = d / f"{t}.csv"
            if f.exists():
                with open(f, newline="", encoding="utf-8", errors="replace") as fh:
                    rows = list(csv.DictReader(fh))
                total[t] = upsert_rows(conn, t, rows)
        conn.commit()
        print("Loaded:", total)
    finally:
        conn.close()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="directory containing Annex C CSVs")
    ap.add_argument("--db", default=None)
    a = ap.parse_args()
    load_dir(a.db, a.dir)
