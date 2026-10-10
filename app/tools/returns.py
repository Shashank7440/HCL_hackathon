"""Return/refund tools - deterministic, thresholds ONLY from rule_registry (R5), Decimal math."""
from __future__ import annotations
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from ..rules.registry import get_rule
from .orders import get_order, customer_tier

def _d(x) -> Decimal: return Decimal(str(x))

def _rule_out(res, applied, conflicts):
    """Collect applied rule + conflict records for the response."""
    if res.winner:
        applied.append({"rule_id": res.winner.rule_id, "value": res.winner.value,
                        "source_doc_id": res.winner.source_doc_id, "source_section": res.winner.source_section})
    if res.losers:
        losers_ids = {l["rule_id"] for l in res.losers}
        conflicts.append({"parameter": res.winner.parameter if res.winner else "",
                           "winner": res.winner.rule_id if res.winner else "",
                           "resolution": [f"{l['rule_id']}: {l['reason']}" for l in res.losers]})
    return res

def check_return_eligibility(conn, customer_id, order_id, sku=None, reason="CHANGED_MIND",
                             as_of=None, tier_override=None) -> dict:
    """State-free check. Never raises; every outcome is a structured result."""
    as_of = as_of or date.today().isoformat()
    applied, conflicts, upcoming = [], [], []
    order_data = get_order(conn, customer_id, order_id)
    if not order_data:
        return {"result": "NOT_AUTHORIZED"}          # caller maps to uniform refusal
    order, items = order_data["order"], order_data["items"]
    item = next((i for i in items if (sku is None or i["sku"] == sku)), None)
    if item is None:
        return {"result": "SKU_NOT_IN_ORDER"}
    tier = tier_override or customer_tier(conn, customer_id)

    def rule(param, cat=None):
        r = get_rule(conn, param, cat, tier, as_of)
        _rule_out(r, applied, conflicts)
        upcoming.extend({"parameter": u.parameter, "rule_id": u.rule_id,
                         "value": u.value, "effective_from": u.effective_from,
                         "source_doc_id": u.source_doc_id} for u in r.upcoming)
        return r

    cat = conn.execute("SELECT category FROM products WHERE sku = ?", (item["sku"],)).fetchone()["category"]

    existing = conn.execute("SELECT * FROM returns WHERE order_id = ? AND sku = ?",
                            (order_id, item["sku"])).fetchone()
    if existing:
        return {"result": "ALREADY_RETURNED", "existing_return": existing["return_id"],
                "status": existing["status"], "applied_rules": applied, "conflicts": conflicts}
    if order["status"] != "DELIVERED" or not item["delivered_on"]:
        return {"result": "NOT_DELIVERED", "order_status": order["status"],
                "applied_rules": applied, "conflicts": conflicts}
    nr = rule("non_returnable", cat)
    if nr.winner and nr.winner.value.lower() == "true":
        return {"result": "NON_RETURNABLE_CATEGORY", "category": cat,
                "applied_rules": applied, "conflicts": conflicts, "upcoming_changes": upcoming}
    w = rule("return_window_days", cat)
    if not w.winner:
        return {"result": "RULE_MISSING", "parameter": "return_window_days",
                "applied_rules": applied, "conflicts": conflicts}
    days = (date.fromisoformat(as_of) - date.fromisoformat(item["delivered_on"])).days
    if days > int(w.winner.value):
        return {"result": "OUT_OF_WINDOW", "days_since_delivery": days,
                "window_days": int(w.winner.value), "category": cat,
                "applied_rules": applied, "conflicts": conflicts, "upcoming_changes": upcoming}
    return {"result": "ELIGIBLE", "days_since_delivery": days,
            "window_days": int(w.winner.value), "category": cat, "tier": tier,
            "assumptions": ([f"Reason not stated: assuming change of mind."] if reason == "CHANGED_MIND" else []),
            "applied_rules": applied, "conflicts": conflicts, "upcoming_changes": upcoming}

def calculate_refund(conn, customer_id, order_id, sku=None, reason="CHANGED_MIND",
                     as_of=None, tier_override=None, eligibility=None) -> dict:
    """Refund = gross - restocking fee (if reason applies; waived for premium tiers) - reverse shipping.
    Uses NET unit price (coupon orders refund what was paid). Decimal everywhere."""
    as_of = as_of or date.today().isoformat()
    tier = tier_override or customer_tier(conn, customer_id)
    if eligibility is None:
        eligibility = check_return_eligibility(conn, customer_id, order_id, sku, reason, as_of, tier)
    if eligibility["result"] not in ("ELIGIBLE", "ALREADY_RETURNED"):
        return eligibility
    applied, conflicts = eligibility.get("applied_rules", []), eligibility.get("conflicts", [])
    upcoming = eligibility.get("upcoming_changes", [])
    order_data = get_order(conn, customer_id, order_id)
    item = order_data["items"][0] if sku is None else \
        next(i for i in order_data["items"] if i["sku"] == sku)

    def rule(param, cat=None):
        r = get_rule(conn, param, cat, tier, as_of)
        _rule_out(r, applied, conflicts)
        upcoming.extend({"parameter": u.parameter, "rule_id": u.rule_id, "value": u.value,
                         "effective_from": u.effective_from, "source_doc_id": u.source_doc_id}
                        for u in r.upcoming)
        return r

    cat = conn.execute("SELECT category FROM products WHERE sku = ?", (item["sku"],)).fetchone()["category"]
    gross = _d(item["net_unit_price"]) * int(item["qty"])
    fee_pct = Decimal("0"); fee = Decimal("0")
    reasons = rule("fee_applicable_reasons")
    if reasons.winner and reason in [x.strip() for x in reasons.winner.value.split(";")]:
        fp = rule("restocking_fee_pct", cat)
        if fp.winner:
            fee_pct = _d(fp.winner.value)
            fee = (gross * fee_pct / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    ship_r = rule("reverse_shipping_fee")
    ship = _d(ship_r.winner.value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if ship_r.winner else Decimal("0")
    refund = gross - fee - ship
    limit_r = rule("auto_refund_limit")
    limit = _d(limit_r.winner.value) if limit_r.winner else None
    return {"result": "ELIGIBLE", "gross_amount": f"{gross:.2f}", "restocking_fee_pct": str(fee_pct),
            "restocking_fee": f"{fee:.2f}", "reverse_shipping_fee": f"{ship:.2f}",
            "refund_amount": f"{refund:.2f}", "requires_human_approval": bool(limit is not None and refund > limit),
            "tier": tier, "applied_rules": applied, "conflicts": conflicts, "upcoming_changes": upcoming}

def raise_return(conn, customer_id, order_id, sku, reason="CHANGED_MIND", as_of=None) -> dict:
    """State-changing tool: checks eligibility ITSELF and is safe to call twice (R5)."""
    as_of = as_of or date.today().isoformat()
    elig = check_return_eligibility(conn, customer_id, order_id, sku, reason, as_of)
    if elig["result"] != "ELIGIBLE":
        return elig
    existing = conn.execute("SELECT * FROM returns WHERE order_id = ? AND sku = ?",
                            (order_id, sku)).fetchone()
    if existing:                                        # idempotent re-call
        return {"result": "ALREADY_RETURNED", "existing_return": existing["return_id"],
                "status": existing["status"]}
    refund = calculate_refund(conn, customer_id, order_id, sku, reason, as_of, eligibility=elig)
    rid = f"R-{conn.execute('SELECT COUNT(*) c FROM returns').fetchone()['c'] + 1:06d}"
    with conn:
        conn.execute("INSERT INTO returns(return_id,order_id,sku,requested_on,reason,status,refund_amount)"
                     " VALUES (?,?,?,?,?,?,?)",
                     (rid, order_id, sku, as_of, reason, "REQUESTED", refund.get("refund_amount")))
    return {"result": "RETURN_RAISED", "return_id": rid, "refund_amount": refund.get("refund_amount"),
            "requires_human_approval": refund.get("requires_human_approval", False)}
