#!/usr/bin/env python3
"""CLI SQLite Database Inspector for ShopEasy data/app.db.
Usage:
    python scripts/query_db.py
    python scripts/query_db.py --table customers
    python scripts/query_db.py --table orders --limit 5
    python scripts/query_db.py --sql "SELECT customer_id, name, membership_tier FROM customers LIMIT 5"
"""
import argparse, sqlite3, sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"

def main():
    parser = argparse.ArgumentParser(description="Query ShopEasy SQLite Database (data/app.db)")
    parser.add_argument("--table", "-t", help="Table name to inspect (customers, orders, products, etc.)", default=None)
    parser.add_argument("--sql", "-s", help="Custom SQL SELECT query to execute", default=None)
    parser.add_argument("--limit", "-n", type=int, default=10, help="Row limit (default: 10)")
    parser.add_argument("--tables", action="store_true", help="List all tables and row counts")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}. Run 'python scripts/seed.py' first.")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if args.tables or (not args.table and not args.sql):
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cursor.fetchall()]
        print("\n=== SQLite Database Tables (data/app.db) ===")
        for t in tables:
            try:
                cnt = cursor.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                print(f"  * {t:<18} ({cnt} rows)")
            except Exception:
                print(f"  * {t:<18}")
        print("\nTip: Run with: python scripts/query_db.py --table customers")
        print("     Or with:   python scripts/query_db.py --table orders")
        print("     Or with:   python scripts/query_db.py --sql \"SELECT * FROM orders LIMIT 5\"\n")
        return

    if args.sql:
        query = args.sql
    else:
        query = f"SELECT * FROM {args.table} LIMIT {args.limit}"

    try:
        cursor.execute(query)
        rows = cursor.fetchall()
        if not rows:
            print("\nNo rows returned.")
            return

        cols = rows[0].keys()
        # Print header
        header = " | ".join(f"{c:<20}" for c in cols)
        print("\n" + header)
        print("-" * len(header))
        for r in rows:
            print(" | ".join(f"{str(r[c])[:19]:<20}" for c in cols))
        print(f"\n({len(rows)} rows shown)\n")
    except Exception as e:
        print(f"Error executing query: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
