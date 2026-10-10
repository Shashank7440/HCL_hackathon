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

ACTIVE_RETURN_STATUSES = ("REQUESTED", "PICKED_UP", "REFUNDED")      # REJECTED does not block a new return

def _pick_item(items, sku):
    """sku given -> that item; one item -> it; several items and no sku -> caller must clarify (None)."""
    if sku:
        return next((i for i in items if i["sku"] == sku), None)
    return items[0] if len(items) == 1 else None

def check_return_eligibility(conn, customer_id, order_id, sku=None, reason="CHANGED_MIND",
                             as_of=None, tier_override=None, delivered_days_override=None) -> dict:
    """Order of checks (our design): ownership -> item -> delivered -> non_returnable -> already returned -> window."""
    as_of = as_of or date.today().isoformat()
    applied, conflicts, upcoming = [], [], []
    order_data = get_order(conn, customer_id, order_id)
    if not order_data:
        return {"result": "NOT_AUTHORIZED"}
    order, items = order_data["order"], order_data["items"]
    item = _pick_item(items, sku)
    if item is None:
        if sku is None and len(items) > 1:
            return {"result": "CLARIFICATION_NEEDED", "items": [i["sku"] for i in items]}
        return {"result": "SKU_NOT_IN_ORDER"}
    tier = tier_override or customer_tier(conn, customer_id)

    def rule(param, cat=None):
        r = get_rule(conn, param, cat, tier, as_of)
        _rule_out(r, applied, conflicts)
        upcoming.extend({"parameter": u.parameter, "rule_id": u.rule_id, "value": u.value,
                         "effective_from": u.effective_from, "source_doc_id": u.source_doc_id} for u in r.upcoming)
        return r

    def out(result, **extra):
        return {"result": result, **extra, "applied_rules": applied, "conflicts": conflicts,
                "upcoming_changes": upcoming}

    cat = conn.execute("SELECT category FROM products WHERE sku = ?", (item["sku"],)).fetchone()["category"]
    if order["status"] != "DELIVERED" or not item["delivered_on"]:
        return out("NOT_DELIVERED", order_status=order["status"])
    nr = rule("non_returnable", cat)
    if nr.status == "unresolved":
        return out("CONFLICT", parameter="non_returnable")
    if nr.winner and nr.winner.value.lower() == "true":
        return out("NON_RETURNABLE_CATEGORY", category=cat)
    existing = conn.execute(
        "SELECT * FROM returns WHERE order_id = ? AND sku = ? AND status IN (?,?,?)",
        (order_id, item["sku"], *ACTIVE_RETURN_STATUSES)).fetchone()
    if existing:
        return out("ALREADY_RETURNED", existing_return=existing["return_id"], status=existing["status"])
    w = rule("return_window_days", cat)
    if w.status == "unresolved":                     # Annex A step 5 -> /ask must answer conflict_flagged
        return out("CONFLICT", parameter="return_window_days",
                   tied=[{"rule_id": t.rule_id, "value": t.value, "source_doc_id": t.source_doc_id} for t in w.tied])
    if not w.winner:
        return out("RULE_MISSING", parameter="return_window_days")
    days = (int(delivered_days_override) if delivered_days_override is not None
            else (date.fromisoformat(as_of) - date.fromisoformat(item["delivered_on"])).days)
    window = int(w.winner.value)
    base = dict(days_since_delivery=days, window_days=window, category=cat, tier=tier, sku=item["sku"])
    if days > window:
        return out("OUT_OF_WINDOW", **base)
    return out("ELIGIBLE", **base,
               assumptions=(["Reason not stated: assuming change of mind."] if reason == "CHANGED_MIND" else []))

def calculate_refund(conn, customer_id, order_id, sku=None, reason="CHANGED_MIND",
                     as_of=None, tier_override=None, eligibility=None, delivered_days_override=None) -> dict:
    """Refund = gross - restocking fee - reverse shipping (both only when the reason is fee-applicable;
    restocking waived by tier-scoped rule). NET unit price, Decimal, round half up, never below 0."""
    as_of = as_of or date.today().isoformat()
    tier = tier_override or customer_tier(conn, customer_id)
    if eligibility is None:
        eligibility = check_return_eligibility(conn, customer_id, order_id, sku, reason, as_of, tier,
                                               delivered_days_override)
    if eligibility["result"] != "ELIGIBLE":          # ALREADY_RETURNED etc. never produce an amount
        return eligibility
    applied, conflicts = eligibility.get("applied_rules", []), eligibility.get("conflicts", [])
    upcoming = eligibility.get("upcoming_changes", [])
    order_data = get_order(conn, customer_id, order_id)
    item = next(i for i in order_data["items"] if i["sku"] == eligibility["sku"])

    def rule(param, cat=None):
        r = get_rule(conn, param, cat, tier, as_of)
        _rule_out(r, applied, conflicts)
        upcoming.extend({"parameter": u.parameter, "rule_id": u.rule_id, "value": u.value,
                         "effective_from": u.effective_from, "source_doc_id": u.source_doc_id} for u in r.upcoming)
        return r

    q2 = lambda x: x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    cat = eligibility["category"]
    gross = _d(item["net_unit_price"]) * int(item["qty"])
    reasons = rule("fee_applicable_reasons")
    # if the fee-reason rule is missing, fees apply to every reason
    fees_apply = (reason in [x.strip() for x in reasons.winner.value.split(";")]) if reasons.winner else True
    fee_pct, fee, ship = Decimal("0"), Decimal("0"), Decimal("0")
    if fees_apply:
        fp = rule("restocking_fee_pct", cat)
        if fp.status == "unresolved":
            return {"result": "CONFLICT", "parameter": "restocking_fee_pct", "applied_rules": applied,
                    "conflicts": conflicts, "upcoming_changes": upcoming}
        if fp.winner:
            fee_pct = _d(fp.winner.value)
            fee = q2(gross * fee_pct / Decimal("100"))
        sr = rule("reverse_shipping_fee")
        if sr.winner:
            ship = q2(_d(sr.winner.value))
    refund = max(gross - fee - ship, Decimal("0"))
    limit_r = rule("auto_refund_limit")
    limit = _d(limit_r.winner.value) if limit_r.winner else None
    return {"result": "ELIGIBLE", "sku": item["sku"], "reason": reason, "gross_amount": f"{gross:.2f}",
            "restocking_fee_pct": str(fee_pct), "restocking_fee": f"{fee:.2f}",
            "reverse_shipping_fee": f"{ship:.2f}", "refund_amount": f"{refund:.2f}",
            "requires_human_approval": bool(limit is not None and refund > limit),
            "tier": tier, "applied_rules": applied, "conflicts": conflicts, "upcoming_changes": upcoming}

def raise_return(conn, customer_id, order_id, sku, reason="CHANGED_MIND", as_of=None) -> dict:
    """State-changing tool: checks eligibility ITSELF and is safe to call twice (R5)."""
    as_of = as_of or date.today().isoformat()
    elig = check_return_eligibility(conn, customer_id, order_id, sku, reason, as_of)
    if elig["result"] != "ELIGIBLE":
        return elig
    existing = conn.execute(
        "SELECT * FROM returns WHERE order_id = ? AND sku = ? AND status IN (?,?,?)",
        (order_id, sku, *ACTIVE_RETURN_STATUSES)).fetchone()
    if existing:                                        # idempotent re-call
        return {"result": "ALREADY_RETURNED", "existing_return": existing["return_id"],
                "status": existing["status"]}
    refund = calculate_refund(conn, customer_id, order_id, sku, reason, as_of, eligibility=elig)
    max_row = conn.execute("SELECT MAX(CAST(substr(return_id,3) AS INTEGER)) m FROM returns").fetchone()
    next_id = (max_row["m"] or 0) + 1 if max_row else 1
    rid = f"R-{next_id:06d}"
    with conn:
        conn.execute("INSERT INTO returns(return_id,order_id,sku,requested_on,reason,status,refund_amount)"
                     " VALUES (?,?,?,?,?,?,?)",
                     (rid, order_id, sku, as_of, reason, "REQUESTED", refund.get("refund_amount")))
    return {"result": "RETURN_RAISED", "return_id": rid, "refund_amount": refund.get("refund_amount"),
            "requires_human_approval": refund.get("requires_human_approval", False)}
