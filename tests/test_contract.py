"""API contract enforcement tests (Section 6 & Annex D)."""
import sys, os, json
from pathlib import Path
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.main import app
from app.config import settings

client = TestClient(app)

CONTRACT_FIELDS = (
    "trace_id", "answer", "answer_type", "citations", "tools_invoked",
    "applied_rules", "conflicts_detected", "assumptions", "explanation",
    "as_of_date", "upcoming_changes"
)

def test_ask_contract_shape():
    res = client.post("/ask", json={"question": "What is the return window for electronics?", "as_of_date": "2026-10-06"})
    assert res.status_code == 200
    data = res.json()
    for field in CONTRACT_FIELDS:
        assert field in data, f"Missing required field {field}"

def test_audit_admin_and_owner_access():
    res = client.post("/ask", json={"question": "How much refund will I get for order O-100001?", "as_of_date": "2026-10-06"},
                      headers={"X-Customer-Id": "C1001"})
    assert res.status_code == 200
    trace_id = res.json()["trace_id"]

    # Owner access: Allowed
    res_owner = client.get(f"/audit/{trace_id}", headers={"X-Customer-Id": "C1001"})
    assert res_owner.status_code == 200
    rec = res_owner.json()["record"]
    assert "latency_ms" in rec
    assert "sources_retrieved" in rec
    assert "question_redacted" in rec

    # Other customer access without admin key: 403 Forbidden
    res_other = client.get(f"/audit/{trace_id}", headers={"X-Customer-Id": "C1002"})
    assert res_other.status_code == 403

    # Admin access: Allowed
    res_admin = client.get(f"/audit/{trace_id}", headers={"X-Admin-Key": settings.ADMIN_KEY})
    assert res_admin.status_code == 200

def test_ingest_bad_date_validation_422():
    # Bad date format in metadata should return 422 Unprocessable Entity
    bad_meta = json.dumps({
        "doc_id": "TEST-BAD",
        "title": "Bad Date Document",
        "authority_level": 2,
        "doc_type": "circular",
        "version": "1.0",
        "effective_from": "not-a-date"
    })
    files = {"file": ("test.md", b"# Test content")}
    data = {"metadata": bad_meta}
    res = client.post("/ingest", files=files, data=data)
    assert res.status_code == 422
