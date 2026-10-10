"""Audit record (R10): build + store + redact. Summary only - no chain-of-thought."""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from .config import settings

def redact_pii(text: str, conn=None) -> str:
    redacted = text
    # Mask emails
    redacted = re.sub(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "[EMAIL]", redacted)
    # Mask phone numbers and 10-19 digit numeric runs (not matching O-xxxxxx or SKU-xxx)
    redacted = re.sub(r"\b(?<!O-)(?<!SKU-)\d{10,19}\b", "[NUMBERS]", redacted)
    redacted = re.sub(r"\b\+?\d{1,3}[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", "[PHONE]", redacted)
    # Mask customer full names from customers table if conn provided
    if conn:
        try:
            names = conn.execute("SELECT name FROM customers").fetchall()
            for r in names:
                name = r["name"]
                if name and len(name) >= 3 and name.lower() in redacted.lower():
                    redacted = re.sub(re.escape(name), "[NAME]", redacted, flags=re.IGNORECASE)
        except Exception:
            pass
    return redacted

def build_record(state: dict, conn=None) -> dict:
    model_name = settings.OLLAMA_MODEL if state.get("llm_calls") else "mock"
    sources = []
    for c in state.get("citations", []):
        sources.append({
            "doc_id": c.get("doc_id", ""),
            "section": c.get("section", ""),
            "score": round(float(c.get("score", 1.0)), 4)
        })
    return {
        "trace_id": state.get("trace_id", ""),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "customer_id": state.get("customer_id"),       # header value only
        "question_category": state.get("intent", ""),
        "question_redacted": redact_pii(state.get("question", ""), conn),
        "sources_retrieved": sources,
        "precedence_decisions": [f"{c.get('winner','')}: {r}" for c in state.get("conflicts_detected", [])
                                 for r in c.get("resolution", [])],
        "tools_invoked": state.get("tools_invoked", []),
        "applied_rules": state.get("applied_rules", []),
        "answer_type": state.get("answer_type", ""),
        "latency_ms": state.get("latency_ms", 0.0),
        "model": model_name,
        "llm_calls": state.get("llm_calls", 0),
        "tokens": state.get("tokens", 0),
    }

def store_record(conn, state: dict) -> None:
    rec = build_record(state, conn)
    with conn:
        conn.execute("INSERT OR REPLACE INTO audit_log VALUES (?,?,?,?)",
                     (rec["trace_id"], rec["customer_id"], rec["timestamp"], json.dumps(rec)))
