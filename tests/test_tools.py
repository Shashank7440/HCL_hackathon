"""Tool tests against the seeded database - FROZEN expected values from the TDD edge table."""
import sys, os, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB_FILE = str(Path(tempfile.gettempdir()) / "test_tools_shopeasy.db")
os.environ["DB_PATH"] = DB_FILE
if Path(DB_FILE).exists():
    Path(DB_FILE).unlink()

from app.db import get_conn, init_schema
from app.tools.returns import check_return_eligibility, calculate_refund, raise_return
from app.tools.warranty import check_warranty
from scripts.load_data import upsert_rows
from scripts.seed import seed

seed(DB_FILE)
conn = get_conn(DB_FILE)
AS_OF = "2026-10-06"

def test_happy_path_refund():
    out = calculate_refund(conn, "C1001", "O-100001", as_of=AS_OF)
    assert out["result"] == "ELIGIBLE", out
    assert out["refund_amount"] == "2639.10", out         # 2999 - 299.90 - 60

def test_defective_refund_no_fees():
    out = calculate_refund(conn, "C1001", "O-100001", reason="DEFECTIVE", as_of=AS_OF)
    assert out["result"] == "ELIGIBLE"
    assert out["restocking_fee"] == "0.00"
    assert out["reverse_shipping_fee"] == "0.00"
    assert out["refund_amount"] == "2999.00"

def test_last_day_eligible():
    out = check_return_eligibility(conn, "C1002", "O-100002", as_of=AS_OF)
    assert out["result"] == "ELIGIBLE" and out["days_since_delivery"] == 7

def test_one_day_late():
    out = check_return_eligibility(conn, "C1003", "O-100003", as_of=AS_OF)
    assert out["result"] == "OUT_OF_WINDOW" and out["days_since_delivery"] == 8

def test_above_approval_limit():
    out = calculate_refund(conn, "C1004", "O-100004", as_of=AS_OF)
    assert out["refund_amount"] == "80931.00" and out["requires_human_approval"] is True

def test_non_returnable_category():
    out = check_return_eligibility(conn, "C1005", "O-100005", as_of=AS_OF)
    assert out["result"] == "NON_RETURNABLE_CATEGORY"

def test_not_delivered():
    out = check_return_eligibility(conn, "C1006", "O-100006", as_of=AS_OF)
    assert out["result"] == "NOT_DELIVERED"

def test_already_returned():
    out = check_return_eligibility(conn, "C1007", "O-100007", as_of=AS_OF)
    assert out["result"] == "ALREADY_RETURNED" and out["existing_return"] == "R-000001"

def test_already_returned_refund_no_amount():
    out = calculate_refund(conn, "C1007", "O-100007", as_of=AS_OF)
    assert out["result"] == "ALREADY_RETURNED"
    assert "refund_amount" not in out

def test_rejected_return_does_not_block():
    conn.execute("INSERT OR REPLACE INTO returns VALUES ('R-999999','O-100001','SKU-E001','2026-10-01','CHANGED_MIND','REJECTED',0)")
    conn.commit()
    out = check_return_eligibility(conn, "C1001", "O-100001", sku="SKU-E001", as_of=AS_OF)
    assert out["result"] == "ELIGIBLE"
    conn.execute("DELETE FROM returns WHERE return_id = 'R-999999'")
    conn.commit()

def test_coupon_net_price():
    out = calculate_refund(conn, "C1013", "O-100013", as_of=AS_OF)
    assert out["gross_amount"] == "3999.00" and out["refund_amount"] == "3539.10"

def test_gold_tier_waiver():
    out = calculate_refund(conn, "C1010", "O-100015", as_of=AS_OF)
    assert out["restocking_fee"] == "0.00" and out["refund_amount"] == "2939.00"

def test_fashion_festive_upcoming_not_applied():
    out = check_return_eligibility(conn, "C1015", "O-100016", as_of=AS_OF)
    assert out["result"] == "ELIGIBLE" and out["window_days"] == 30
    assert any(u["rule_id"] == "RET-WIN-FASH-02" for u in out["upcoming_changes"])

def test_warranty_expired_and_valid_boundary():
    assert check_warranty(conn, "C1011", "O-100011", as_of=AS_OF)["result"] == "EXPIRED"
    assert check_warranty(conn, "C1012", "O-100012", as_of=AS_OF)["result"] == "VALID"

def test_delivered_days_override_warranty_boundary():
    out_elig = check_return_eligibility(conn, "C1001", "O-100001", as_of=AS_OF, delivered_days_override=41)
    assert out_elig["result"] == "OUT_OF_WINDOW"
    out_war = check_warranty(conn, "C1001", "O-100001", as_of=AS_OF, delivered_days_override=41)
    assert out_war["result"] == "VALID"

def test_ownership_enforced_in_tool():
    assert check_return_eligibility(conn, "C1001", "O-100002", as_of=AS_OF)["result"] == "NOT_AUTHORIZED"
    assert calculate_refund(conn, "C1001", "O-999999", as_of=AS_OF)["result"] == "NOT_AUTHORIZED"

def test_raise_return_idempotent():
    out = raise_return(conn, "C1001", "O-100001", "SKU-E001", as_of=AS_OF)
    assert out["result"] == "RETURN_RAISED"
    out2 = raise_return(conn, "C1001", "O-100001", "SKU-E001", as_of=AS_OF)
    assert out2["result"] == "ALREADY_RETURNED" and out2["existing_return"] == out["return_id"]
    conn.execute("DELETE FROM returns WHERE order_id = 'O-100001'")
    conn.commit()
