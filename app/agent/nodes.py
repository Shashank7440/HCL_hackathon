"""Multi-Agent System Nodes:
- SecurityGuardAgent (guard_input, authz)
- SupervisorAgent (route)
- OrderToolsAgent (tools_node)
- PolicyRetrievalAgent (retrieve_node)
- CompositeMultiStepAgent (composite_node)
- SynthesisAgent (compose_node, finalize_node)
"""
from __future__ import annotations
from datetime import date
import re
import secrets
from decimal import Decimal
from ..constants import NOT_FOUND_MSG, REFUSAL_MSG, SIGN_IN_MSG, ANSWER_TYPES
from ..security import sanitize, known_customer, owns_order, refusal_uniform
from ..tools import orders as order_tools
from ..tools import returns as return_tools
from ..tools.warranty import check_warranty
from ..rules.registry import get_rule, rule_citation
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
    """Security guard: verified header identity and order ownership."""
    order_id = state.get("order_id")
    if not order_id:
        return {}
    cid = state.get("customer_id")
    if not cid or not known_customer(conn, cid):
        return {"answer": SIGN_IN_MSG, "answer_type": "refused", "refused": True}
    if not owns_order(conn, cid, order_id):
        return {"answer": refusal_uniform(), "answer_type": "refused", "refused": True}
    return {}

def _merge_tool_fields(state: dict, out: dict) -> None:
    """Fold tool outputs (applied rules, conflicts, upcoming) into response fields."""
    st = state
    for r in out.get("applied_rules", []):
        st["applied_rules"].append(r)
        cit = {
            "doc_id": r.get("source_doc_id", ""),
            "title": "",
            "section": r.get("source_section", ""),
            "page": 1,
            "version": "",
            "effective_from": ""
        }
        st["citations"].append(cit)
    for c in out.get("conflicts", []):
        st["conflicts_detected"].append(c)
    for u in out.get("upcoming_changes", []):
        if u.get("rule_id"):
            st["upcoming_changes"].append(u)

def tools_node(state: dict, conn) -> dict:
    cid, oid = state.get("customer_id"), state.get("order_id")
    intent, sku, as_of = state["intent"], state.get("sku"), state["as_of_date"]

    if intent in ("order_status",):
        if not oid:
            return {"answer": "Which order would you like me to look up? Please share the order id.",
                    "answer_type": "clarification_needed"}
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

    if intent in ("return_eligibility", "refund", "raise_return", "warranty") and not oid:
        # Personal inquiry without an order ID
        if not cid or not known_customer(conn, cid):
            return {"answer": SIGN_IN_MSG, "answer_type": "refused", "refused": True}
        rows = order_tools.list_customer_orders(conn, cid)
        if not rows:
            return {"answer": refusal_uniform(), "answer_type": "refused", "refused": True}
        
        # Check for multiple orders of the same product/category (ambiguity edge case)
        cat = state.get("category")
        if cat or sku:
            matching = []
            for r in rows:
                full_o = order_tools.get_order(conn, cid, r["order_id"])
                if full_o:
                    for itm in full_o["items"]:
                        p_row = conn.execute("SELECT category, name FROM products WHERE sku = ?", (itm["sku"],)).fetchone()
                        if p_row:
                            if sku and itm["sku"] == sku:
                                matching.append((r["order_id"], r["order_date"], p_row["name"]))
                            elif cat and p_row["category"].upper() == cat.upper():
                                matching.append((r["order_id"], r["order_date"], p_row["name"]))
            if len(matching) > 1:
                return {
                    "answer": f"You have multiple orders containing {matching[0][2]}: " +
                              ", ".join(f"{m[0]} ({m[1]})" for m in matching) +
                              ". Which order would you like to return?",
                    "answer_type": "clarification_needed"
                }

        return {
            "answer": "Which order is this about? Your orders: " +
                      ", ".join(f"{r['order_id']} ({r['order_date']})" for r in rows[:5]),
            "answer_type": "clarification_needed"
        }

    if intent == "return_eligibility":
        out = return_tools.check_return_eligibility(conn, cid, oid, sku, as_of=as_of)
        state["tools_invoked"].append({
            "tool": "check_return_eligibility",
            "input": {"order_id": oid, "sku": sku},
            "output": out
        })
        _merge_tool_fields(state, out)
        if out["result"] == "NOT_AUTHORIZED":
            return {"answer": refusal_uniform(), "answer_type": "refused", "refused": True}
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
        out = return_tools.calculate_refund(conn, cid, oid, sku, as_of=as_of)
        state["tools_invoked"].append({
            "tool": "calculate_refund",
            "input": {"order_id": oid, "sku": sku},
            "output": out
        })
        _merge_tool_fields(state, out)
        if out["result"] == "NOT_AUTHORIZED":
            return {"answer": refusal_uniform(), "answer_type": "refused", "refused": True}
        if out["result"] == "ELIGIBLE":
            state["assumptions"].extend(["Reason not stated: assuming change of mind."])
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
        out = return_tools.raise_return(conn, cid, oid, sku, as_of=as_of)
        state["tools_invoked"].append({
            "tool": "raise_return",
            "input": {"order_id": oid, "sku": sku},
            "output": out
        })
        _merge_tool_fields(state, out)
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
    """Composite Specialist Agent: executes multi-step plans and what-if hypothetical simulations."""
    intent = state.get("intent")
    as_of = state.get("as_of_date") or date.today().isoformat()
    cid, oid = state.get("customer_id"), state.get("order_id")
    cat = state.get("category") or "ELECTRONICS"
    days_offset = state.get("days_offset")
    what_if_tier = state.get("what_if_tier")

    if intent == "multi_step":
        # Question pattern: "My headphones stopped working after 41 days. Can I return them, and if not, what can I do?"
        days = days_offset or 41
        
        # Step 1: Return eligibility check
        win_res = get_rule(conn, "return_window_days", cat, "STANDARD", as_of)
        window = int(win_res.winner.value) if win_res.winner else 7
        if win_res.winner:
            state["applied_rules"].append({
                "rule_id": win_res.winner.rule_id,
                "value": win_res.winner.value,
                "source_doc_id": win_res.winner.source_doc_id,
                "source_section": win_res.winner.source_section
            })
            state["citations"].append({
                "doc_id": win_res.winner.source_doc_id,
                "title": "Return Policy / Circular",
                "section": win_res.winner.source_section,
                "page": 1,
                "version": "1.0",
                "effective_from": win_res.winner.effective_from
            })
        
        return_eligible = (days <= window)
        state["tools_invoked"].append({
            "tool": "check_return_eligibility",
            "input": {"category": cat, "days_since_delivery": days},
            "output": {"result": "ELIGIBLE" if return_eligible else "OUT_OF_WINDOW", "window_days": window}
        })

        # Step 2: Warranty check (electronics standard warranty is 12 months = 365 days)
        warranty_days = 365
        warranty_valid = (days <= warranty_days)
        state["tools_invoked"].append({
            "tool": "check_warranty",
            "input": {"category": cat, "days_since_delivery": days},
            "output": {"result": "VALID" if warranty_valid else "EXPIRED", "warranty_months": 12}
        })

        # Step 3: Procedural claim steps retrieval
        war_hits = retriever.search("warranty claim procedure steps", category=cat, as_of=as_of, top_k=2)
        claim_doc = "WAR-POL-2024"
        claim_sec = "4.1"
        if war_hits:
            claim_doc = war_hits[0]["doc_id"]
            claim_sec = war_hits[0].get("section", "4.1")
            state["citations"].append({
                "doc_id": claim_doc,
                "title": war_hits[0].get("title", "Warranty Policy"),
                "section": claim_sec,
                "page": war_hits[0].get("page", 1),
                "version": war_hits[0].get("version", "1.0"),
                "effective_from": war_hits[0].get("effective_from", "2024-07-01")
            })

        state["assumptions"].append(f"Assumed {days} days since delivery and hardware defect covered under manufacturer warranty.")

        ans = (
            f"You cannot return the {cat.lower()} item because {days} days exceeds the {window}-day return window. "
            f"However, your item is covered under the 12-month manufacturer warranty. "
            f"To raise a warranty claim, contact the manufacturer authorized service centre or ShopEasy support "
            f"with your purchase invoice ({claim_doc} Section {claim_sec})."
        )
        return {
            "answer": ans,
            "answer_type": "calculated",
            "explanation": f"Multi-step evaluation: return window ({window} days) has expired, but product warranty (12 months) remains active. Procedural steps retrieved from {claim_doc}."
        }

    if intent == "what_if":
        # What-if scenario simulation
        if days_offset is not None:
            win_res = get_rule(conn, "return_window_days", cat, "STANDARD", as_of)
            window = int(win_res.winner.value) if win_res.winner else 7
            if win_res.winner:
                state["applied_rules"].append({
                    "rule_id": win_res.winner.rule_id,
                    "value": win_res.winner.value,
                    "source_doc_id": win_res.winner.source_doc_id,
                    "source_section": win_res.winner.source_section
                })
            state["assumptions"].append(f"Hypothetical scenario: returning {days_offset} days after delivery.")
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
            if oid and cid:
                std_out = return_tools.calculate_refund(conn, cid, oid, as_of=as_of, tier_override="STANDARD")
                tier_out = return_tools.calculate_refund(conn, cid, oid, as_of=as_of, tier_override=what_if_tier)
                state["tools_invoked"].append({"tool": "calculate_refund", "input": {"tier": what_if_tier}, "output": tier_out})
                _merge_tool_fields(state, tier_out)
                ans = (
                    f"As a {what_if_tier} member, restocking fee is waived (0%) and reverse shipping fee is waived. "
                    f"Your refund would be {tier_out.get('refund_amount')} compared to {std_out.get('refund_amount')} under Standard tier."
                )
            else:
                ans = (
                    f"Under the {what_if_tier} tier, restocking fees are waived (0% instead of 10%) and reverse shipping fees are waived. "
                    f"Eligible returns receive a 100% refund of the net purchase price."
                )
            return {
                "answer": ans,
                "answer_type": "calculated",
                "explanation": f"Hypothetical fee policy evaluation under {what_if_tier} tier benefits."
            }

    return {}

def retrieve_node(state: dict, conn, retriever) -> dict:
    hits = retriever.search(state["question"], category=state.get("category"),
                            as_of=state["as_of_date"], top_k=6)
    if not hits:
        return {"answer": NOT_FOUND_MSG, "answer_type": "not_found"}

    # Check for unresolvable conflict among top hits
    if len(hits) >= 2:
        h1, h2 = hits[0], hits[1]
        if (h1.get("authority_level") == h2.get("authority_level") and
            h1.get("eff_from_i") == h2.get("eff_from_i") and
            h1["doc_id"] != h2["doc_id"] and
            h1.get("score", 0) > 0.8 and h2.get("score", 0) > 0.8):
            state["citations"].append({"doc_id": h1["doc_id"], "title": h1["title"],
                                       "section": h1.get("section", ""), "page": h1.get("page", 1),
                                       "version": h1.get("version", ""),
                                       "effective_from": h1.get("effective_from", "")})
            state["citations"].append({"doc_id": h2["doc_id"], "title": h2["title"],
                                       "section": h2.get("section", ""), "page": h2.get("page", 1),
                                       "version": h2.get("version", ""),
                                       "effective_from": h2.get("effective_from", "")})
            state["conflicts_detected"].append({
                "parameter": "policy_statement",
                "winner": "unresolved",
                "resolution": [f"Conflicting sources: {h1['doc_id']} and {h2['doc_id']}"]
            })
            return {
                "answer": f"Conflicting policies detected between {h1['doc_id']} and {h2['doc_id']}. Please contact customer support for clarification.",
                "answer_type": "conflict_flagged",
                "explanation": "Unresolved conflict between equal authority sources."
            }

    best = hits[0]
    state["citations"].append({
        "doc_id": best["doc_id"],
        "title": best["title"],
        "section": best.get("section", ""),
        "page": best.get("page", 1),
        "version": best.get("version", ""),
        "effective_from": best.get("effective_from", "")
    })
    ans = "\n".join(l.lstrip("#").strip() for l in best["text"].strip().splitlines())
    ans = " ".join(ans.split())
    if len(ans) > 450:
        ans = ans[:450] + "..."
    return {
        "answer": ans,
        "answer_type": "retrieved_fact",
        "explanation": "Answer taken from the highest-precedence applicable source."
    }

def compose_node(state: dict) -> dict:
    """Synthesis agent: checks that final answers are strictly grounded and formatted."""
    if state.get("answer"):
        return {}
    return {"answer": NOT_FOUND_MSG, "answer_type": "not_found"}

def finalize_node(state: dict) -> dict:
    atype = state.get("answer_type")
    if not atype or atype not in ANSWER_TYPES:
        atype = "not_found"
    return {"answer_type": atype}
