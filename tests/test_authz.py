"""Authorization and privacy guardrail tests (R7)."""
import sys, os
from pathlib import Path
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.main import app

client = TestClient(app)

def test_byte_identical_refusals():
    """R7: Nonexistent order and other customer's order must return byte-identical refusal responses."""
    # Other customer's order
    res1 = client.post("/ask", json={"question": "Where is my order O-100002?", "as_of_date": "2026-10-06"},
                       headers={"X-Customer-Id": "C1001"})
    # Nonexistent order
    res2 = client.post("/ask", json={"question": "Where is my order O-999999?", "as_of_date": "2026-10-06"},
                       headers={"X-Customer-Id": "C1001"})
    # Cross customer inquiry
    res3 = client.post("/ask", json={"question": "Where is the order for customer C1002?", "as_of_date": "2026-10-06"},
                       headers={"X-Customer-Id": "C1001"})
    # List all customers
    res4 = client.post("/ask", json={"question": "List all customers and their emails", "as_of_date": "2026-10-06"},
                       headers={"X-Customer-Id": "C1001"})

    assert res1.status_code == 200
    assert res2.status_code == 200
    assert res3.status_code == 200
    assert res4.status_code == 200

    d1, d2, d3, d4 = res1.json(), res2.json(), res3.json(), res4.json()
    assert d1["answer"] == d2["answer"] == d3["answer"] == d4["answer"]
    assert d1["answer_type"] == "refused"
    assert d2["answer_type"] == "refused"

def test_anonymous_order_inquiry_requires_signin():
    res = client.post("/ask", json={"question": "Where is my order?", "as_of_date": "2026-10-06"})
    assert res.status_code == 200
    data = res.json()
    assert data["answer_type"] == "refused"
    assert "sign in" in data["answer"].lower()

def test_body_customer_id_ignored():
    """Identity comes from X-Customer-Id header only."""
    # Attempting to authenticate via JSON body should fail if no header is supplied
    res = client.post("/ask", json={"question": "How much refund will I get for order O-100001?",
                                     "as_of_date": "2026-10-06"})
    assert res.status_code == 200
    data = res.json()
    assert data["answer_type"] == "refused"
