#!/usr/bin/env python3
"""Idempotent seed: schema + source register + rules + CSVs. Run once at setup."""
import csv, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import get_conn, init_schema
from app.ingestion.pipeline import ingest_document
from app.retrieval.store import VectorStore

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
AS_OF_DEFAULT = "2024-07-01"

def seed(db_path: str | None = None) -> None:
    init_schema(db_path)
    conn = get_conn(db_path)
    try:
        # 1. source register -> documents rows (docs text ingested separately once files exist)
        with open(DATA / "source_register.csv", newline="", encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                conn.execute("""INSERT OR REPLACE INTO documents(doc_id,title,issuer,authority_level,
                    doc_type,version,effective_from,effective_to,supersedes,scope_categories,scope_tiers,
                    provenance,retrieved_on,synthetic) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r["doc_id"], r["title"], r["issuer"], int(r["authority_level"]), r["doc_type"],
                     r["version"], r["effective_from"], r["effective_to"], r["supersedes"],
                     r["scope_categories"], r["scope_tiers"], r["provenance"], r["retrieved_on"], r["synthetic"]))
        # 2. rules from the combined seed CSV
        with open(DATA / "seed_csv" / "rule_registry_seed.csv", newline="", encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                conn.execute("""INSERT OR REPLACE INTO rule_registry(rule_id,description,parameter,operator,
                    value,scope_categories,scope_tiers,effective_from,effective_to,source_doc_id,
                    source_section,auto_extracted) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r["rule_id"], r["description"], r["parameter"], r["operator"], r["value"],
                     r["scope_categories"], r["scope_tiers"], r["effective_from"], r["effective_to"],
                     r["source_doc_id"], r["source_section"], int(r.get("auto_extracted", 0) or 0)))
        conn.commit()
        # 3. seed documents (md files) through the SAME ingest pipeline
        store = VectorStore(conn)
        for md in sorted((DATA / "docs").glob("*.md")):
            meta_path = DATA / "docs_meta" / f"{md.stem}_meta.json"
            rules_path = DATA / "docs_meta" / f"{md.stem}_rules.json"
            meta = json.loads(meta_path.read_text()) if meta_path.exists() else None
            if meta:
                rules = json.loads(rules_path.read_text()) if rules_path.exists() else []
                out = ingest_document(conn, store, str(md), md.name, meta, rules)
                print("ingested", out)
    finally:
        conn.close()
    # 4. customer/order CSVs via the shared loader (upsert, judges' ids accepted)
    sys.path.insert(0, str(ROOT / "scripts"))
    from load_data import load_dir
    load_dir(db_path, str(DATA / "seed_csv"))

if __name__ == "__main__":
    import os
    seed(os.getenv("DB_PATH"))
