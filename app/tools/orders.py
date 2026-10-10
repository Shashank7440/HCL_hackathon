"""Order tools. Identity from guard only; ownership re-checked in every tool (defense in depth)."""
from __future__ import annotations

def get_order(conn, customer_id: str, order_id: str) -> dict | None:
    """Returns the order ONLY if it belongs to caller; None otherwise (uniform refusal upstream)."""
    row = conn.execute("SELECT * FROM orders WHERE order_id = ? AND customer_id = ?",
                       (order_id, customer_id)).fetchone()
    if not row: return None
    items = [dict(r) for r in conn.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,))]
    return {"order": dict(row), "items": items}

def list_customer_orders(conn, customer_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM orders WHERE customer_id = ? ORDER BY order_date DESC", (customer_id,))]

def customer_tier(conn, customer_id: str) -> str:
    row = conn.execute("SELECT tier FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()
    return row["tier"] if row else "STANDARD"
