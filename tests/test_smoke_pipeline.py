"""End-to-end smoke (no FastAPI needed): seed docs through the ingest pipeline,
then run the fallback graph on the 5 demo questions + one LIVE ingest that changes an answer."""
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
import os
os.environ["DB_PATH"] = "/tmp/smoke_shopeasy.db"
if Path("/tmp/smoke_shopeasy.db").exists(): Path("/tmp/smoke_shopeasy.db").unlink()
from app.db import get_conn, init_schema
from app.ingestion.pipeline import ingest_document
from app.retrieval.store import VectorStore
from app.retrieval.retriever import Retriever
from app.agent.graph import _run_nodes
from scripts.seed import seed

seed("/tmp/smoke_shopeasy.db")
conn = get_conn("/tmp/smoke_shopeasy.db")
conn.close()
conn = get_conn("/tmp/smokeasy.db") if False else get_conn("/tmp/smokeasy.db".replace("smokeasy","smoke_shopeasy"))
AS_OF = "2026-10-06"

def ask(question, customer_id=None, as_of=AS_OF):
    conn = get_conn("/tmp/smoke_shopeasy.db")
    try:
        return _run_nodes({"question": question, "customer_id": customer_id, "as_of_date": as_of}, conn, Retriever(conn))
    finally:
        conn.close()

def test_policy_fact_electronics():
    s = ask("What is the return window for electronics?")
    assert s["answer_type"] == "retrieved_fact", s
    assert "7 days" in s["answer"].lower() or "7 calendar days" in s["answer"].lower(), s["answer"]
    assert s["citations"][0]["doc_id"] == "CIRC-2026-07", s["citations"]

def test_personal_refund():
    s = ask("How much refund will I get for order O-100001?", customer_id="C1001")
    assert s["answer_type"] == "calculated", s
    assert "2639.10" in s["answer"], s["answer"]
    assert any(t["tool"] == "calculate_refund" for t in s["tools_invoked"])

def test_other_customers_order_refused():
    s = ask("Where is my order O-100002?", customer_id="C1001")
    assert s["answer_type"] == "refused" and s["answer"] == "I can't help with that request for this account.", s

def test_nonexistent_order_same_refusal():
    s = ask("Where is my order O-999999?", customer_id="C1001")
    assert s["answer_type"] == "refused" and s["answer"] == "I can't help with that request for this account.", s

def test_unanswerable():
    s = ask("Do you deliver to Antarctica?")
    assert s["answer_type"] == "not_found"
    assert s["answer"] == "I could not find this information in the authorised sources."

def test_zz_last_live_ingest_changes_answer():
    # a brand-new circular shortens the electronics window to 5 days, effective BEFORE as_of
    new_md = Path("/tmp/CIRC-2026-10.md")
    new_md.write_text("# Circular: Electronics Window Update (CIRC-2026-10)\n\n"
        "## 1 Electronics return window is 5 days\n"
        "Effective from 2026-10-01, the ELECTRONICS return window is 5 calendar days. "
        "This supersedes CIRC-2026-07.\n")
    conn = get_conn("/tmp/smoke_shopeasy.db")
    try:
        out = ingest_document(conn, VectorStore(conn), str(new_md), "CIRC-2026-10.md",
            {"doc_id": "CIRC-2026-10", "title": "Electronics Window Update",
             "authority_level": 2, "doc_type": "circular", "version": "1.0",
             "effective_from": "2026-10-01", "supersedes": "CIRC-2026-07",
             "scope_categories": "ELECTRONICS", "scope_tiers": "ALL"},
            [{"rule_id": "RET-WIN-ELEC-03", "description": "Electronics window 5 days",
              "parameter": "return_window_days", "operator": "=", "value": "5",
              "scope_categories": "ELECTRONICS", "scope_tiers": "ALL",
              "effective_from": "2026-10-01", "source_section": "1"}])
        assert out["chunks_indexed"] > 0 and out["status"] == "indexed", out
    finally:
        conn.close()
    s = ask("How much refund will I get for order O-100001?", customer_id="C1001")
    # O-100001 delivered 3 days ago; 5-day window still eligible, but the O-100002 customer
    # (7 days) must now be OUT_OF_WINDOW - proving the live rule change reached the tool
    s2 = ask("Can I return my item from order O-100002?", customer_id="C1002")
    assert s2["answer_type"] == "calculated" and "OUT OF WINDOW" in s2["answer"].upper(), s2["answer"]
    # and the policy answer now cites the new circular
    s3 = ask("What is the return window for electronics?")
    assert s3["citations"][0]["doc_id"] == "CIRC-2026-10", s3["citations"]

if __name__ == "__main__":
    for name, fn in sorted({k: v for k, v in globals().items() if k.startswith("test_")}.items()):
        fn(); print(f"PASS {name}")
    print("ALL SMOKE TESTS PASSED")
