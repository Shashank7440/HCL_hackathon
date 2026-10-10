"""Warranty tool - deterministic date math over products.warranty_months."""
from __future__ import annotations
from datetime import date, timedelta
from .orders import get_order

def check_warranty(conn, customer_id, order_id, sku=None, as_of=None, delivered_days_override=None) -> dict:
    as_of = as_of or date.today().isoformat()
    order_data = get_order(conn, customer_id, order_id)
    if not order_data: return {"result": "NOT_AUTHORIZED"}
    item = next((i for i in order_data["items"] if sku is None or i["sku"] == sku), None)
    if item is None: return {"result": "SKU_NOT_IN_ORDER"}
    row = conn.execute("SELECT name, warranty_months FROM products WHERE sku = ?", (item["sku"],)).fetchone()
    months = row["warranty_months"]
    if months == 0:
        return {"result": "NO_WARRANTY", "sku": item["sku"], "warranty_months": months}
    if delivered_days_override is not None:      # "stopped working after 41 days"
        dl = date.fromisoformat(as_of) - timedelta(days=int(delivered_days_override))
    elif item["delivered_on"]:
        dl = date.fromisoformat(item["delivered_on"])
    else:
        return {"result": "NOT_DELIVERED", "sku": item["sku"], "warranty_months": months}
    y, m = dl.year + months // 12, dl.month + months % 12
    if m > 12: y, m = y + 1, m - 12
    try: end = date(y, m, dl.day)
    except ValueError: end = date(y, m, 28)              # e.g. Nov 31 -> 28
    valid = end >= date.fromisoformat(as_of)
    return {"result": "VALID" if valid else "EXPIRED", "sku": item["sku"],
            "delivered_on": dl.isoformat(), "warranty_end": end.isoformat(),
            "warranty_months": months}
