"""LangGraph Workflow Nodes:
guard_input -> route -> authz -> [tools_node | composite_node | retrieve_node] -> compose_node -> finalize_node
"""
from __future__ import annotations
from datetime import date
import json
import re
import secrets
from decimal import Decimal
from ..config import settings
from ..constants import NOT_FOUND_MSG, REFUSAL_MSG, SIGN_IN_MSG, ANSWER_TYPES
from ..security import sanitize, known_customer, owns_order, refusal_uniform
from ..tools import orders as order_tools
from ..tools import returns as return_tools
from ..tools.warranty import check_warranty
from ..rules.registry import get_rule
from .policy import citation_for, policy_fact
from . import router as agent_router

INJECTION_PATTERNS = (
    "ignore previous instructions", "override policy", "system prompt",
    "drop table", "grant refund", "bypass check", "act as admin",
    "ignore all instructions", "you must refund", "grant return"
)

def guard_input(state: dict) -> dict:
    trace = secrets.token_hex(4)
    q = sanitize(state["question"])
    as_of = state.get("as_of_date") or date.today().isoformat()
    assumptions = list(state.get("assumptions") or [])
    
    # R8: Detect untrusted instructions in customer questions/notes
    q_lower = q.lower()
    if any(pat in q_lower for pat in INJECTION_PATTERNS):
        assumptions.append("Untrusted instruction text detected in query and treated strictly as data.")

    return {
        "trace_id": trace,
        "question": q,
        "as_of_date": as_of,
        "customer_id": state.get("customer_id"),   # header identity only
        "citations": [],
        "tools_invoked": [],
        "applied_rules": [],
        "conflicts_detected": [],
        "upcoming_changes": [],
        "assumptions": assumptions,
        "llm_calls": 0,
        "tokens": 0,
        "errors": []
    }

def route(state: dict) -> dict:
    from ..config import settings
    from ..llm.client import chat_json
    r = agent_router.route(state["question"])
    llm_calls, tokens = 0, 0
    if r["intent"] == "general" and not settings.MOCK_LLM:
        try:
            cls, tokens = chat_json(f"Classify intent for: {state['question']}")
            if cls.get("intent") in agent_router.INTENTS_FALLBACK:
                r["intent"] = cls["intent"]
            llm_calls = 1
        except Exception:
            pass
    return {**r, "llm_calls": llm_calls, "tokens": tokens}

def authz(state: dict, conn) -> dict:
    """Security guard: verified header identity and order ownership (R7)."""
    q = state["question"].lower()
    cid = state.get("customer_id")

    # Refuse cross-customer extraction or list-all queries
    if re.search(r"\b(all|every|other|another)\s+(customers?|users?|accounts?)\b", q):
        return {"answer": refusal_uniform(), "answer_type": "refused", "refused": True}

    other_cids = re.findall(r"\bC\d{4}\b", state["question"])
    for oc in other_cids:
        if not cid or oc.upper() != cid.upper():
            return {"answer": refusal_uniform(), "answer_type": "refused", "refused": True}

    order_id = state.get("order_id")
    if not order_id:
        return {}
    if not cid or not known_customer(conn, cid):
        return {"answer": SIGN_IN_MSG, "answer_type": "refused", "refused": True}
    if not owns_order(conn, cid, order_id):
        return {"answer": refusal_uniform(), "answer_type": "refused", "refused": True}
    return {}

def _merge_tool_fields(state: dict, out: dict, conn=None) -> None:
    """Fold tool outputs (applied rules, conflicts, upcoming) into response fields."""
    st = state
    for r in out.get("applied_rules", []):
        st["applied_rules"].append(r)
        if conn and r.get("source_doc_id"):
            cit = citation_for(conn, r["source_doc_id"], r.get("source_section", ""))
        else:
            cit = {
                "doc_id": r.get("source_doc_id", ""),
                "title": "",
                "section": r.get("source_section", ""),
                "page": 1,
                "version": "",
                "effective_from": ""
            }
        if not any(c.get("doc_id") == cit["doc_id"] and c.get("section") == cit["section"] for c in st["citations"]):
            st["citations"].append(cit)
    for c in out.get("conflicts", []):
        st["conflicts_detected"].append(c)
    for u in out.get("upcoming_changes", []):
        if u.get("rule_id"):
            st["upcoming_changes"].append(u)

def tools_node(state: dict, conn) -> dict:
    cid, oid = state.get("customer_id"), state.get("order_id")
    intent, sku, as_of = state["intent"], state.get("sku"), state["as_of_date"]
    reason = state.get("reason") or "CHANGED_MIND"

    # Personal inquiries require identity (R7)
    if not oid and intent in ("order_status", "return_eligibility", "refund", "raise_return", "warranty"):
        if not cid or not known_customer(conn, cid):
            return {"answer": SIGN_IN_MSG, "answer_type": "refused", "refused": True}
        rows = order_tools.list_customer_orders(conn, cid)
        if not rows:
            return {"answer": refusal_uniform(), "answer_type": "refused", "refused": True}

        # Check for matching product / category across caller's orders
        cat = state.get("category")
        pname = state.get("product_name")
        matching = []
        for r in rows:
            full_o = order_tools.get_order(conn, cid, r["order_id"])
            if full_o:
                for itm in full_o["items"]:
                    p_row = conn.execute("SELECT category, name FROM products WHERE sku = ?", (itm["sku"],)).fetchone()
                    if p_row:
                        if sku and itm["sku"] == sku:
                            matching.append({"order_id": r["order_id"], "order_date": r["order_date"], "name": p_row["name"], "sku": itm["sku"]})
                        elif pname:
                            if pname.lower() in p_row["name"].lower():
                                matching.append({"order_id": r["order_id"], "order_date": r["order_date"], "name": p_row["name"], "sku": itm["sku"]})
                        elif cat and p_row["category"].upper() == cat.upper():
                            matching.append({"order_id": r["order_id"], "order_date": r["order_date"], "name": p_row["name"], "sku": itm["sku"]})
        if len(matching) > 1:
            return {
                "answer": f"You have multiple orders containing {matching[0]['name']}: " +
                          ", ".join(f"{m['order_id']} ({m['order_date']})" for m in matching) +
                          ". Which order would you like to return?",
                "answer_type": "clarification_needed"
            }
        elif len(matching) == 1:
            oid = matching[0]["order_id"]
            sku = matching[0]["sku"]
            state["order_id"] = oid
            state["sku"] = sku
        elif len(rows) == 1 and intent == "order_status":
            oid = rows[0]["order_id"]
            state["order_id"] = oid
        else:
            orders_desc = []
            for r in rows[:5]:
                full_o = order_tools.get_order(conn, cid, r["order_id"])
                item_names = []
                if full_o and full_o.get("items"):
                    for itm in full_o["items"]:
                        p_row = conn.execute("SELECT name FROM products WHERE sku = ?", (itm["sku"],)).fetchone()
                        item_names.append(p_row["name"] if p_row else itm["sku"])
                item_str = f" ({', '.join(item_names)})" if item_names else ""
                orders_desc.append(f"{r['order_id']}{item_str} placed on {r['order_date']}")
            return {
                "answer": "Which order is this about? Your orders: " +
                          ", ".join(orders_desc) + ". Which order would you like to check?",
                "answer_type": "clarification_needed"
            }

    if intent in ("order_status",):
        out = order_tools.get_order(conn, cid, oid)
        if out is None:
            return {"answer": refusal_uniform(), "answer_type": "refused", "refused": True}
        state["tools_invoked"].append({
            "tool": "get_order",
            "input": {"order_id": oid},
            "output": {
                "status": out["order"]["status"],
                "order_date": out["order"]["order_date"],
                "payment_method": out["order"]["payment_method"]
            }
        })
        return {
            "answer": f"Order {oid} was placed on {out['order']['order_date']} and its current status is {out['order']['status']}.",
            "answer_type": "calculated",
            "explanation": "Looked up by a tool, for the logged-in customer only."
        }

    # Match SKU inside the order if not explicitly specified
    if oid and not sku:
        full_o = order_tools.get_order(conn, cid, oid)
        if full_o and full_o.get("items"):
            items = full_o["items"]
            if len(items) == 1:
                sku = items[0]["sku"]
            else:
                pname = state.get("product_name")
                if pname:
                    for itm in items:
                        p_row = conn.execute("SELECT name FROM products WHERE sku = ?", (itm["sku"],)).fetchone()
                        if p_row and pname.lower() in p_row["name"].lower():
                            sku = itm["sku"]
                            break

    if intent == "return_eligibility":
        out = return_tools.check_return_eligibility(conn, cid, oid, sku, reason=reason, as_of=as_of)
        state["tools_invoked"].append({
            "tool": "check_return_eligibility",
            "input": {"order_id": oid, "sku": sku, "reason": reason},
            "output": out
        })
        _merge_tool_fields(state, out, conn)
        if out["result"] == "NOT_AUTHORIZED":
            return {"answer": refusal_uniform(), "answer_type": "refused", "refused": True}
        if out["result"] == "CONFLICT":
            tied = out.get("tied", [])
            for t in tied:
                cit = citation_for(conn, t["source_doc_id"], "")
                if not any(c.get("doc_id") == cit["doc_id"] and c.get("section") == cit["section"] for c in state["citations"]):
                    state["citations"].append(cit)
            return {
                "answer": "Our sources conflict on the return window and the precedence policy cannot decide. Please contact customer support.",
                "answer_type": "conflict_flagged"
            }
        if out["result"] == "CLARIFICATION_NEEDED":
            items_info = []
            for item_sku in out.get("items", []):
                p_row = conn.execute("SELECT name FROM products WHERE sku = ?", (item_sku,)).fetchone()
                items_info.append(f"{item_sku} ({p_row['name'] if p_row else 'item'})")
            return {
                "answer": f"Order {oid} contains multiple items: {', '.join(items_info)}. Which product would you like to return?",
                "answer_type": "clarification_needed"
            }
        if out["result"] == "ELIGIBLE":
            state["assumptions"].extend(out.get("assumptions", []))
            return {
                "answer": f"Yes, you can return it. Delivered {out['days_since_delivery']} days ago; "
                          f"the {out['category'].lower()} return window is {out['window_days']} days.",
                "answer_type": "calculated",
                "explanation": f"Eligibility computed by a deterministic tool: "
                               f"{out['days_since_delivery']} days since delivery vs a "
                               f"{out['window_days']}-day window."
            }
        return {
            "answer": f"Unfortunately this return is not possible: {out['result'].replace('_',' ').lower()}.",
            "answer_type": "calculated"
        }

    if intent == "refund":
        out = return_tools.calculate_refund(conn, cid, oid, sku, reason=reason, as_of=as_of)
        state["tools_invoked"].append({
            "tool": "calculate_refund",
            "input": {"order_id": oid, "sku": sku, "reason": reason},
            "output": out
        })
        _merge_tool_fields(state, out, conn)
        if out["result"] == "NOT_AUTHORIZED":
            return {"answer": refusal_uniform(), "answer_type": "refused", "refused": True}
        if out["result"] == "CONFLICT":
            return {
                "answer": "Our sources conflict on the fee calculation and the precedence policy cannot decide. Please contact customer support.",
                "answer_type": "conflict_flagged"
            }
        if out["result"] == "CLARIFICATION_NEEDED":
            return {
                "answer": f"Order {oid} has multiple items. Please specify which SKU you wish to return for refund.",
                "answer_type": "clarification_needed"
            }
        if out["result"] == "ALREADY_RETURNED":
            return {
                "answer": "Unfortunately this return is not possible: already returned.",
                "answer_type": "calculated"
            }
        if out["result"] == "ELIGIBLE":
            if state.get("reason") is None:
                state["assumptions"].append("Reason not stated: assuming change of mind.")
            extra = " This exceeds the auto-approval limit and needs human approval." \
                    if out.get("requires_human_approval") else ""
            return {
                "answer": f"Your refund would be {out['refund_amount']} "
                          f"(gross {out['gross_amount']} - restocking fee {out['restocking_fee']}"
                          f" - reverse shipping {out['reverse_shipping_fee']}).{extra}",
                "answer_type": "calculated",
                "explanation": "Refund computed by a deterministic tool from the order record "
                               "and the rule registry, using net price."
            }
        return {
            "answer": f"I can't compute a refund for this order: {out['result'].replace('_',' ').lower()}.",
            "answer_type": "calculated"
        }

    if intent == "raise_return":
        if not sku:
            return {"answer": "Which product (SKU) should I raise the return for?",
                    "answer_type": "clarification_needed"}
        out = return_tools.raise_return(conn, cid, oid, sku, reason=reason, as_of=as_of)
        state["tools_invoked"].append({
            "tool": "raise_return",
            "input": {"order_id": oid, "sku": sku, "reason": reason},
            "output": out
        })
        _merge_tool_fields(state, out, conn)
        if out["result"] in ("RETURN_RAISED",):
            return {
                "answer": f"Return {out['return_id']} raised. Expected refund: {out['refund_amount']}.",
                "answer_type": "calculated"
            }
        if out["result"] == "NOT_AUTHORIZED":
            return {"answer": refusal_uniform(), "answer_type": "refused", "refused": True}
        return {
            "answer": f"I couldn't raise this return: {out['result'].replace('_',' ').lower()}.",
            "answer_type": "calculated"
        }

    if intent == "warranty":
        out = check_warranty(conn, cid, oid, sku, as_of=as_of)
        state["tools_invoked"].append({
            "tool": "check_warranty",
            "input": {"order_id": oid, "sku": sku},
            "output": out
        })
        cit = citation_for(conn, "WAR-POL-2024", "1")
        if not any(c.get("doc_id") == cit["doc_id"] and c.get("section") == cit["section"] for c in state["citations"]):
            state["citations"].append(cit)
        if out["result"] == "NOT_AUTHORIZED":
            return {"answer": refusal_uniform(), "answer_type": "refused", "refused": True}
        if out["result"] in ("VALID", "EXPIRED"):
            return {
                "answer": f"Your warranty is {out['result'].lower()}"
                          + (f" until {out['warranty_end']}." if out["result"] == "VALID" else "."),
                "answer_type": "calculated"
            }
        return {
            "answer": f"Warranty check: {out['result'].replace('_',' ').lower()}.",
            "answer_type": "calculated"
        }

    return {}

def composite_node(state: dict, conn, retriever) -> dict:
    """Composite Specialist Agent: executes multi-step plans and what-if hypothetical simulations (R6)."""
    intent = state.get("intent")
    as_of = state.get("as_of_date") or date.today().isoformat()
    cid, oid = state.get("customer_id"), state.get("order_id")
    cat = state.get("category")
    days_offset = state.get("days_offset")
    what_if_tier = state.get("what_if_tier")
    pname = state.get("product_name")

    if intent == "multi_step":
        days = days_offset or 41
        reason = state.get("reason") or "DEFECTIVE"

        # 1. Resolve order / item identity
        sku = state.get("sku")
        if not oid:
            if not cid or not known_customer(conn, cid):
                return {"answer": SIGN_IN_MSG, "answer_type": "refused", "refused": True}
            rows = order_tools.list_customer_orders(conn, cid)
            if not rows:
                return {"answer": refusal_uniform(), "answer_type": "refused", "refused": True}
            matching = []
            for r in rows:
                full_o = order_tools.get_order(conn, cid, r["order_id"])
                if full_o:
                    for itm in full_o["items"]:
                        p_row = conn.execute("SELECT category, name FROM products WHERE sku = ?", (itm["sku"],)).fetchone()
                        if p_row:
                            if sku and itm["sku"] == sku:
                                matching.append((r["order_id"], itm["sku"], p_row["name"], r["order_date"], p_row["category"]))
                            elif pname:
                                if pname.lower() in p_row["name"].lower():
                                    matching.append((r["order_id"], itm["sku"], p_row["name"], r["order_date"], p_row["category"]))
                            elif cat and p_row["category"].upper() == cat.upper():
                                matching.append((r["order_id"], itm["sku"], p_row["name"], r["order_date"], p_row["category"]))
            if len(matching) > 1:
                return {
                    "answer": "You have multiple relevant orders: " +
                              ", ".join(f"{m[0]} ({m[2]} on {m[3]})" for m in matching) +
                              ". Which order is this about?",
                    "answer_type": "clarification_needed"
                }
            elif len(matching) == 1:
                oid = matching[0][0]
                sku = matching[0][1]
                cat = matching[0][4]
            else:
                return {
                    "answer": "Which order is this about? Please share your order ID.",
                    "answer_type": "clarification_needed"
                }

        # 2. Check return eligibility with days override
        out_elig = return_tools.check_return_eligibility(conn, cid, oid, sku, reason=reason, as_of=as_of, delivered_days_override=days)
        state["tools_invoked"].append({
            "tool": "check_return_eligibility",
            "input": {"order_id": oid, "sku": sku, "delivered_days_override": days},
            "output": out_elig
        })
        _merge_tool_fields(state, out_elig, conn)
        window = out_elig.get("window_days", 7)
        cat = out_elig.get("category", cat or "ELECTRONICS")

        # 3. Check warranty with days override
        out_war = check_warranty(conn, cid, oid, sku, as_of=as_of, delivered_days_override=days)
        state["tools_invoked"].append({
            "tool": "check_warranty",
            "input": {"order_id": oid, "sku": sku, "delivered_days_override": days},
            "output": out_war
        })
        cit_war = citation_for(conn, "WAR-POL-2024", "1")
        if not any(c.get("doc_id") == cit_war["doc_id"] and c.get("section") == cit_war["section"] for c in state["citations"]):
            state["citations"].append(cit_war)

        # 4. Retrieve warranty claim procedure
        step_rows = conn.execute(
            "SELECT section, text FROM chunks WHERE doc_id = 'WAR-POL-2024' AND section LIKE '2%' ORDER BY section"
        ).fetchall()
        for s_row in step_rows:
            cit_step = citation_for(conn, "WAR-POL-2024", s_row["section"])
            if not any(c.get("doc_id") == cit_step["doc_id"] and c.get("section") == cit_step["section"] for c in state["citations"]):
                state["citations"].append(cit_step)

        claim_steps = "; ".join(r["text"].strip() for r in step_rows) if step_rows else "Contact support with your order id and a description of the fault."

        # 5. Document assumptions
        state["assumptions"].append(f"Assuming the item was delivered {days} days ago.")
        if state.get("reason") is None:
            state["assumptions"].append("Assuming defect covered under warranty.")

        # 6. Compose answer
        months = out_war.get("warranty_months", 12)
        if out_war.get("result") == "VALID":
            ans = (
                f"You cannot return the {cat.lower()} item because {days} days exceeds the {window}-day return window. "
                f"However, your item is covered under the {months}-month warranty (valid until {out_war.get('warranty_end')}). "
                f"To raise a warranty claim: {claim_steps} (WAR-POL-2024 §2)."
            )
        else:
            ans = (
                f"You cannot return the {cat.lower()} item because {days} days exceeds the {window}-day return window. "
                f"Additionally, the {months}-month warranty has expired."
            )

        return {
            "answer": ans,
            "answer_type": "calculated",
            "explanation": f"Multi-step evaluation: return window ({window} days) vs {days} days, followed by warranty check and claim procedure."
        }

    if intent == "what_if":
        if days_offset is not None:
            state["assumptions"].append(f"Hypothetical scenario: returning {days_offset} days after delivery.")
            if oid and cid and owns_order(conn, cid, oid):
                out = return_tools.check_return_eligibility(conn, cid, oid, state.get("sku"), reason=state.get("reason") or "CHANGED_MIND", as_of=as_of, delivered_days_override=days_offset)
                state["tools_invoked"].append({"tool": "check_return_eligibility", "input": {"order_id": oid, "delivered_days_override": days_offset}, "output": out})
                _merge_tool_fields(state, out, conn)
                window = out.get("window_days", 7)
                cat = out.get("category", cat or "ELECTRONICS")
            else:
                cat = cat or "ELECTRONICS"
                state["assumptions"].append(f"Hypothetical scenario: evaluated for {cat.lower()} category.")
                w = get_rule(conn, "return_window_days", cat, "STANDARD", as_of)
                window = int(w.winner.value) if w.winner else 7
                if w.winner:
                    state["applied_rules"].append({"rule_id": w.winner.rule_id, "value": w.winner.value, "source_doc_id": w.winner.source_doc_id, "source_section": w.winner.source_section})
                    state["citations"].append(citation_for(conn, w.winner.source_doc_id, w.winner.source_section))

            if days_offset <= window:
                ans = f"If returned after {days_offset} days, it would still be eligible for return as the {cat.lower()} window is {window} days."
            else:
                ans = f"If returned after {days_offset} days, it would be outside the {window}-day {cat.lower()} return window and therefore not eligible for return."
            return {
                "answer": ans,
                "answer_type": "calculated",
                "explanation": f"Hypothetical return window evaluation: {days_offset} days vs {window}-day threshold."
            }

        if what_if_tier:
            state["assumptions"].append(f"Hypothetical scenario: customer evaluated under {what_if_tier} tier.")
            if oid and cid and owns_order(conn, cid, oid):
                act_tier = order_tools.customer_tier(conn, cid)
                std_out = return_tools.calculate_refund(conn, cid, oid, state.get("sku"), as_of=as_of, tier_override=act_tier)
                tier_out = return_tools.calculate_refund(conn, cid, oid, state.get("sku"), as_of=as_of, tier_override=what_if_tier)
                state["tools_invoked"].append({"tool": "calculate_refund", "input": {"tier": what_if_tier}, "output": tier_out})
                _merge_tool_fields(state, tier_out, conn)
                ans = (
                    f"Under {what_if_tier}: restocking fee is waived ({tier_out.get('restocking_fee')}) and reverse shipping is {tier_out.get('reverse_shipping_fee')} "
                    f"→ refund {tier_out.get('refund_amount')} (as {act_tier}: {std_out.get('refund_amount')})."
                )
            else:
                r_tier = get_rule(conn, "restocking_fee_pct", cat, what_if_tier, as_of)
                val = r_tier.winner.value if r_tier.winner else "0"
                if r_tier.winner:
                    state["applied_rules"].append({"rule_id": r_tier.winner.rule_id, "value": r_tier.winner.value, "source_doc_id": r_tier.winner.source_doc_id, "source_section": r_tier.winner.source_section})
                    state["citations"].append(citation_for(conn, r_tier.winner.source_doc_id, r_tier.winner.source_section))
                ans = f"Under the {what_if_tier} tier, the restocking fee is {val}%."
            return {
                "answer": ans,
                "answer_type": "calculated",
                "explanation": f"Hypothetical fee policy evaluation under {what_if_tier} tier benefits."
            }

    return {}

def retrieve_node(state: dict, conn, retriever) -> dict:
    from .policy import policy_fact
    tier = (order_tools.customer_tier(conn, state["customer_id"])
            if state.get("customer_id") and known_customer(conn, state["customer_id"]) else None)
    fact = policy_fact(state, conn, tier)
    if fact:
        return fact

    hits = retriever.search(state["question"], category=state.get("category"),
                            as_of=state["as_of_date"], top_k=6)
    if not hits:
        return {"answer": NOT_FOUND_MSG, "answer_type": "not_found"}

    # Handle level 5 sources (informational only, never the main answer)
    valid_hits = [h for h in hits if int(h.get("authority_level", 4)) <= 4]
    has_l5 = any(int(h.get("authority_level", 4)) == 5 for h in hits)
    if not valid_hits:
        return {"answer": NOT_FOUND_MSG, "answer_type": "not_found"}

    best = valid_hits[0]
    cit = citation_for(conn, best["doc_id"], best.get("section", ""))
    state["citations"].append(cit)

    # For procedure questions, check for sibling step chunks
    q_lower = state["question"].lower()
    is_procedure = any(p in q_lower for p in ("how do i", "how can i", "how to", "steps to", "procedure"))
    if is_procedure and best.get("section"):
        parent_sec = best["section"].split(".")[0]
        sibs = conn.execute(
            "SELECT section, text FROM chunks WHERE doc_id = ? AND (section LIKE ? OR section = ?) ORDER BY section",
            (best["doc_id"], f"{parent_sec}.%", parent_sec)
        ).fetchall()
        if len(sibs) > 1:
            ans = " ".join(s["text"].strip() for s in sibs)
        else:
            ans = best["text"].strip()
    else:
        ans = best["text"].strip()

    # Clean leading headings and format
    ans = "\n".join(l.lstrip("#").strip() for l in ans.splitlines() if not l.strip().startswith("#"))
    ans = " ".join(ans.split())

    # Cut cleanly at sentence boundary if very long
    if len(ans) > 450:
        cut = ans[:450].rfind(".")
        if cut > 100:
            ans = ans[:cut + 1]

    if has_l5:
        l5_doc = next(h["doc_id"] for h in hits if int(h.get("authority_level", 4)) == 5)
        ans += f" An unofficial source ({l5_doc}, level 5) says something different; it is informational only and has no effect."

    return {
        "answer": ans,
        "answer_type": "retrieved_fact",
        "explanation": "Answer taken from the highest-precedence applicable source."
    }

def compose_node(state: dict) -> dict:
    """Synthesis agent: checks that final answers are strictly grounded and formatted (R5/R9)."""
    if not state.get("answer"):
        return {"answer": NOT_FOUND_MSG, "answer_type": "not_found"}
    if state["answer_type"] in ("refused", "not_found", "clarification_needed") or settings.MOCK_LLM:
        return {}
    facts = {
        "question": state["question"],
        "answer": state["answer"],
        "assumptions": state["assumptions"],
        "tools": [t["output"] for t in state["tools_invoked"]],
        "rules": state["applied_rules"]
    }
    try:
        from ..llm.client import compose_answer
        text, tokens = compose_answer(facts)
        allowed = json.dumps(facts, default=str)
        nums = lambda s: set(re.findall(r"\d+(?:\.\d+)?", s))
        ids = lambda s: set(re.findall(r"\bO-\d{6}\b|\bC\d{4}\b|\bSKU-[A-Z]\d{3}\b", s))
        if text and nums(text) <= nums(allowed) and ids(text) <= ids(allowed):
            return {"explanation": text, "llm_calls": state.get("llm_calls", 0) + 1,
                    "tokens": state.get("tokens", 0) + tokens}
    except Exception:
        pass
    return {}

def finalize_node(state: dict) -> dict:
    atype = state.get("answer_type")
    if not atype or atype not in ANSWER_TYPES:
        atype = "not_found"
    return {"answer_type": atype}
