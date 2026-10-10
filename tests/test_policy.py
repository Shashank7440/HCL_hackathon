"""Policy rule resolution tests via Annex A engine (R1-R4)."""
import sys, os, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB_FILE = str(Path(tempfile.gettempdir()) / "test_policy_shopeasy.db")
os.environ["DB_PATH"] = DB_FILE
if Path(DB_FILE).exists():
    Path(DB_FILE).unlink()

from app.db import get_conn
from app.agent.policy import policy_fact
from scripts.seed import seed

seed(DB_FILE)
conn = get_conn(DB_FILE)

def test_electronics_window_and_conflict():
    state = {"question": "What is the return window for electronics?", "category": "ELECTRONICS",
             "as_of_date": "2026-10-06", "citations": [], "applied_rules": [],
             "conflicts_detected": [], "upcoming_changes": []}
    out = policy_fact(state, conn)
    assert out is not None
    assert "7 days" in out["answer"]
    assert any(c["doc_id"] == "CIRC-2026-07" for c in state["citations"])
    assert len(state["conflicts_detected"]) > 0

def test_fashion_window_upcoming_not_applied():
    state = {"question": "What is the return window for fashion products?", "category": "FASHION",
             "as_of_date": "2026-10-06", "citations": [], "applied_rules": [],
             "conflicts_detected": [], "upcoming_changes": []}
    out = policy_fact(state, conn)
    assert out is not None
    assert "30 days" in out["answer"]
    assert any(u["rule_id"] == "RET-WIN-FASH-02" for u in state["upcoming_changes"])
    # Not applied
    assert not any(r["rule_id"] == "RET-WIN-FASH-02" for r in state["applied_rules"])

def test_past_date_as_of_2026_07_01():
    state = {"question": "What is the return window for electronics?", "category": "ELECTRONICS",
             "as_of_date": "2026-07-01", "citations": [], "applied_rules": [],
             "conflicts_detected": [], "upcoming_changes": []}
    out = policy_fact(state, conn)
    assert out is not None
    assert "10 days" in out["answer"]
    assert any(c["doc_id"] == "RET-POL-2024" for c in state["citations"])

def test_categoryless_window_clarification():
    state = {"question": "What is the return window?", "category": None,
             "as_of_date": "2026-10-06", "citations": [], "applied_rules": [],
             "conflicts_detected": [], "upcoming_changes": []}
    out = policy_fact(state, conn)
    assert out is not None
    assert out["answer_type"] == "clarification_needed"
    assert "category" in out["answer"].lower()

def test_unresolved_tied_rules_flag_conflict():
    # Insert two tied rules with same authority and date
    with conn:
        conn.execute("INSERT OR REPLACE INTO documents(doc_id,title,authority_level,version,effective_from) "
                     "VALUES ('CIRC-TIED-1','Tied Circ 1',2,'1.0','2026-10-01')")
        conn.execute("INSERT OR REPLACE INTO documents(doc_id,title,authority_level,version,effective_from) "
                     "VALUES ('CIRC-TIED-2','Tied Circ 2',2,'1.0','2026-10-01')")
        conn.execute("INSERT OR REPLACE INTO rule_registry(rule_id,parameter,value,scope_categories,scope_tiers,effective_from,source_doc_id,source_section) "
                     "VALUES ('RULE-T1','test_param','10','ALL','ALL','2026-10-01','CIRC-TIED-1','1')")
        conn.execute("INSERT OR REPLACE INTO rule_registry(rule_id,parameter,value,scope_categories,scope_tiers,effective_from,source_doc_id,source_section) "
                     "VALUES ('RULE-T2','test_param','20','ALL','ALL','2026-10-01','CIRC-TIED-2','1')")
    from app.rules.registry import get_rule
    res = get_rule(conn, "test_param", "ALL", "STANDARD", "2026-10-06")
    assert res.status == "unresolved"
    assert len(res.tied) == 2
