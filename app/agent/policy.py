"""Policy facts answered from the rule registry through the Annex A resolver (R1-R4).
Text retrieval is only the fallback when no registered parameter matches the question."""
from __future__ import annotations
import re
from ..rules.registry import get_rule

PARAMS = (   # specific parameters first, generic "window" wording last
    ("restocking_fee_pct",   r"restocking"),
    ("reverse_shipping_fee", r"reverse shipping|return shipping|pick.?up fee"),
    ("auto_refund_limit",    r"approval limit|auto.?refund|human approval"),
    ("non_returnable",       r"non.?returnable|cannot be returned|can i return (grocery|food|groceries)"),
    ("return_window_days",   r"window|how long|how many days|days (do|to)|deadline|return period|send back|give back|\d+\s*days"),
)
LABEL = {"return_window_days": ("return window", "days"), "restocking_fee_pct": ("restocking fee", "%"),
         "reverse_shipping_fee": ("reverse shipping fee", "INR"),
         "auto_refund_limit": ("refund auto-approval limit", "INR"), "non_returnable": ("non-returnable status", "")}
NEEDS_CATEGORY = ("return_window_days", "non_returnable")

def detect_parameter(question: str) -> str | None:
    return next((p for p, rx in PARAMS if re.search(rx, question, re.I)), None)

def citation_for(conn, doc_id: str, section: str) -> dict:
    """Full citation (R2) built by code from the register + chunk table - never by the LLM."""
    d = conn.execute("SELECT title, version, effective_from FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    c = conn.execute("SELECT page FROM chunks WHERE doc_id = ? AND section = ? LIMIT 1", (doc_id, section)).fetchone()
    return {"doc_id": doc_id, "title": d["title"] if d else "", "section": section or "",
            "page": c["page"] if c else 1, "version": d["version"] if d else "",
            "effective_from": d["effective_from"] if d else ""}

def policy_fact(state: dict, conn, tier: str | None = None) -> dict | None:
    """Returns a partial state, or None to fall back to chunk retrieval."""
    param = detect_parameter(state["question"])
    if not param:
        return None
    cat, as_of = state.get("category"), state["as_of_date"]
    if param in NEEDS_CATEGORY and not cat:
        return {"answer": "Which product category do you mean (electronics, fashion, home, beauty or grocery)?",
                "answer_type": "clarification_needed"}
    res = get_rule(conn, param, cat, tier, as_of)
    label, unit = LABEL[param]
    if res.status == "unresolved":                                    # Annex A step 5
        for t in res.tied:
            state["citations"].append(citation_for(conn, t.source_doc_id, t.source_section))
        state["conflicts_detected"].append({"parameter": param, "winner": "unresolved",
            "resolution": [f"{t.rule_id} ({t.source_doc_id}): {t.value}" for t in res.tied]})
        return {"answer": f"Our sources conflict on the {label} and the precedence policy cannot decide. "
                          "Please contact customer support.", "answer_type": "conflict_flagged"}
    if not res.winner:
        return None
    w = res.winner
    subject = f"{cat.lower()} " if cat else ""
    if param == "non_returnable":
        answer = f"{(cat or '').title()} items are non-returnable ({w.source_doc_id} §{w.source_section})."
    else:
        answer = f"The {subject}{label} is {w.value}{'' if unit == '%' else ' '}{unit} " \
                 f"({w.source_doc_id} §{w.source_section}, effective {w.effective_from})."
    for u in res.upcoming:                                            # R4: mention, never apply
        answer += f" Upcoming change: {u.value}{'' if unit == '%' else ' '}{unit} from {u.effective_from} " \
                  f"({u.source_doc_id}); it is not in effect on {as_of}."
        state["upcoming_changes"].append({"parameter": param, "rule_id": u.rule_id, "value": u.value,
                                          "effective_from": u.effective_from, "source_doc_id": u.source_doc_id})
    state["applied_rules"].append({"rule_id": w.rule_id, "value": w.value,
                                   "source_doc_id": w.source_doc_id, "source_section": w.source_section})
    state["citations"].append(citation_for(conn, w.source_doc_id, w.source_section))
    if res.losers:
        state["conflicts_detected"].append({"parameter": param, "winner": w.rule_id,
            "resolution": [f"{l['rule_id']}: {l['reason']}" for l in res.losers]})
    return {"answer": answer, "answer_type": "retrieved_fact",
            "explanation": f"Resolved with the Annex A precedence policy as of {as_of}."}
