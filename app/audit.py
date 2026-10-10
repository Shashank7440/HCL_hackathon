"""Audit record (R10): build + store + redact. Summary only - no chain-of-thought."""
from __future__ import annotations
import json
from datetime import datetime, timezone

def build_record(state: dict) -> dict:
    return {
        "trace_id": state.get("trace_id", ""),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "customer_id": state.get("customer_id"),       # header value only; question is redacted-free below
        "question_category": state.get("intent", ""),
        "question_redacted": (state.get("question", "")[:120]),
        "sources_retrieved": [c.get("doc_id","") for c in state.get("citations", [])],
        "precedence_decisions": [f"{c.get('winner','')}: {r}" for c in state.get("conflicts_detected", [])
                                 for r in c.get("resolution", [])],
        "tools_invoked": state.get("tools_invoked", []),
        "applied_rules": state.get("applied_rules", []),
        "answer_type": state.get("answer_type", ""),
        "model": "mock" if not state.get("llm_calls") else "ollama",
        "llm_calls": state.get("llm_calls", 0),
        "tokens": state.get("tokens", 0),
    }

def store_record(conn, state: dict) -> None:
    rec = build_record(state)
    with conn:
        conn.execute("INSERT OR REPLACE INTO audit_log VALUES (?,?,?,?)",
                     (rec["trace_id"], rec["customer_id"], rec["timestamp"], json.dumps(rec)))
