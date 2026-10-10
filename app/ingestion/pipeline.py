"""ingest_document(file, metadata, rules): parse -> chunk -> index -> upsert docs+rules.
Synchronous; usable by the very next /ask. Idempotent (same doc_id replaces)."""
from __future__ import annotations
import json, time
from datetime import date
from ..config import settings
from ..db import get_conn
from ..retrieval.store import VectorStore

META_FIELDS = ("doc_id","title","issuer","authority_level","doc_type","version","effective_from",
               "effective_to","supersedes","scope_categories","scope_tiers","provenance",
               "retrieved_on","synthetic")

def ingest_document(conn, store: VectorStore, file_path: str, filename: str,
                    metadata: dict, rules: list[dict]) -> dict:
    doc_id = metadata["doc_id"]
    existed = conn.execute("SELECT 1 FROM documents WHERE doc_id = ?", (doc_id,)).fetchone() is not None
    pages = parse(file_path, filename)
    if not any(p.text.strip() for p in pages):
        raise ValueError("EMPTY_DOCUMENT")
    from .chunker import chunk_pages
    chunks = chunk_pages(doc_id, metadata["title"], pages)
    if not rules and settings.AUTO_EXTRACT_RULES:
        rules = extract_rules_from_pages(doc_id, metadata, pages)
    meta = {k: metadata.get(k, "" if k not in ("authority_level",) else 4) for k in META_FIELDS}
    with conn:
        # idempotent replace: remove old chunks + rules, then upsert doc row (FK target)
        store.delete_doc(doc_id)
        conn.execute("DELETE FROM rule_registry WHERE source_doc_id = ?", (doc_id,))
        conn.execute("""INSERT OR REPLACE INTO documents(doc_id,title,issuer,authority_level,doc_type,
            version,effective_from,effective_to,supersedes,scope_categories,scope_tiers,provenance,
            retrieved_on,synthetic,chunks_indexed,ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (doc_id, metadata["title"], metadata.get("issuer",""), int(metadata.get("authority_level",4)),
             metadata.get("doc_type",""), metadata["version"], metadata["effective_from"],
             metadata.get("effective_to","") or "", metadata.get("supersedes","") or "",
             metadata.get("scope_categories","ALL"), metadata.get("scope_tiers","ALL"),
             metadata.get("provenance",""), metadata.get("retrieved_on",""),
             metadata.get("synthetic","N"), len(chunks), date.today().isoformat()))
        n_rules = 0
        for r in rules:
            conn.execute("""INSERT OR REPLACE INTO rule_registry(rule_id,description,parameter,operator,
                value,scope_categories,scope_tiers,effective_from,effective_to,source_doc_id,source_section,
                auto_extracted) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r["rule_id"], r.get("description",""), r["parameter"], r.get("operator","="),
                 str(r["value"]), r.get("scope_categories","ALL"), r.get("scope_tiers","ALL"),
                 r.get("effective_from") or metadata["effective_from"],
                 r.get("effective_to") or metadata.get("effective_to","") or "",
                 r.get("source_doc_id") or doc_id, r.get("source_section",""),
                 int(r.get("auto_extracted", 0))))
            n_rules += 1
    store.upsert_chunks([dict(c, version=metadata["version"],
                             authority_level=int(metadata.get("authority_level", 4)),
                             effective_from=metadata["effective_from"],
                             effective_to=metadata.get("effective_to","") or "",
                             scope_categories=metadata.get("scope_categories","ALL"),
                             scope_tiers=metadata.get("scope_tiers","ALL")) for c in chunks])
    return {"doc_id": doc_id, "chunks_indexed": len(chunks),
            "status": "replaced" if existed else "indexed", "rules_upserted": n_rules}

def parse(file_path: str, filename: str):
    from .parsers import parse_file
    return parse_file(file_path, filename)

def parse_rules_field(raw) -> list[dict]:
    """Tolerant rules parsing: JSON string or file, array or {"rules": [...]}. Also accepts file part."""
    if raw is None: return []
    if hasattr(raw, "read"): raw = raw.read().decode("utf-8", errors="ignore")
    if isinstance(raw, bytes): raw = raw.decode("utf-8", errors="ignore")
    if not str(raw).strip(): return []
    data = json.loads(raw)
    if isinstance(data, dict) and "rules" in data: data = data["rules"]
    if not isinstance(data, list): raise ValueError("VALIDATION_ERROR: rules must be an array")
    return data

def extract_rules_from_pages(doc_id: str, metadata: dict, pages) -> list[dict]:
    import re
    full_text = "\n".join(p.text for p in pages)
    extracted = []
    # 1. Return windows by category or general
    for cat in ("ELECTRONICS", "FASHION", "HOME", "BEAUTY", "GROCERY"):
        pattern = rf"(?:return\s+window\s+(?:for\s+{cat}\s+)?(?:is\s+|shortened\s+to\s+|reduced\s+to\s+|changed\s+to\s+|set\s+to\s+)(\d+)\s*(?:calendar\s*)?days|{cat}\s*(?:items|products)?\s*(?:may\s+be\s+returned|can\s+be\s+returned)?\s*(?:within|is)\s+(\d+)\s*(?:calendar\s*)?days)"
        m = re.search(pattern, full_text, re.I)
        if m:
            val = m.group(1) or m.group(2)
            extracted.append({
                "rule_id": f"AUTO-{doc_id}-RET-WIN-{cat}",
                "description": f"Auto-extracted return window {val} days for {cat}",
                "parameter": "return_window_days",
                "operator": "=",
                "value": str(val),
                "scope_categories": cat,
                "scope_tiers": metadata.get("scope_tiers", "ALL"),
                "effective_from": metadata.get("effective_from"),
                "effective_to": metadata.get("effective_to", "") or "",
                "source_doc_id": doc_id,
                "source_section": "1",
                "auto_extracted": 1,
            })
    # general return window if no category-specific matched
    if not extracted:
        m = re.search(r"return\s+window\s+(?:is\s+|shortened\s+to\s+|reduced\s+to\s+|changed\s+to\s+|set\s+to\s+)(\d+)\s*(?:calendar\s*)?days", full_text, re.I)
        if m:
            scope = metadata.get("scope_categories", "ALL")
            extracted.append({
                "rule_id": f"AUTO-{doc_id}-RET-WIN-GEN",
                "description": f"Auto-extracted return window {m.group(1)} days for {scope}",
                "parameter": "return_window_days",
                "operator": "=",
                "value": str(m.group(1)),
                "scope_categories": scope,
                "scope_tiers": metadata.get("scope_tiers", "ALL"),
                "effective_from": metadata.get("effective_from"),
                "effective_to": metadata.get("effective_to", "") or "",
                "source_doc_id": doc_id,
                "source_section": "1",
                "auto_extracted": 1,
            })
    # 2. Restocking fee
    m = re.search(r"restocking\s+fee\s+(?:is\s+|of\s+|charged\s+at\s+)(\d+(?:\.\d+)?)\s*%", full_text, re.I)
    if m:
        extracted.append({
            "rule_id": f"AUTO-{doc_id}-FEE",
            "description": f"Auto-extracted restocking fee {m.group(1)}%",
            "parameter": "restocking_fee_pct",
            "operator": "=",
            "value": str(m.group(1)),
            "scope_categories": metadata.get("scope_categories", "ALL"),
            "scope_tiers": metadata.get("scope_tiers", "ALL"),
            "effective_from": metadata.get("effective_from"),
            "effective_to": metadata.get("effective_to", "") or "",
            "source_doc_id": doc_id,
            "source_section": "1",
            "auto_extracted": 1,
        })
    # 3. Reverse shipping fee
    m = re.search(r"reverse\s+shipping\s+fee\s+(?:is\s+|of\s+|charged\s+at\s+)(\d+(?:\.\d+)?)", full_text, re.I)
    if m:
        extracted.append({
            "rule_id": f"AUTO-{doc_id}-SHIP",
            "description": f"Auto-extracted reverse shipping fee {m.group(1)}",
            "parameter": "reverse_shipping_fee",
            "operator": "=",
            "value": str(m.group(1)),
            "scope_categories": metadata.get("scope_categories", "ALL"),
            "scope_tiers": metadata.get("scope_tiers", "ALL"),
            "effective_from": metadata.get("effective_from"),
            "effective_to": metadata.get("effective_to", "") or "",
            "source_doc_id": doc_id,
            "source_section": "1",
            "auto_extracted": 1,
        })
    return extracted
