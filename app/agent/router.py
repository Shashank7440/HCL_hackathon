"""Supervisor Router: Regex-first entity extraction, category keyword expansion,
multi-step and what-if intent detection, with LLM fallback only when intent is unclassified."""
from __future__ import annotations
import re

ORDER_RE = re.compile(r"\bO-\d{6}\b")
SKU_RE = re.compile(r"\bSKU-[A-Z]\d{3}\b")
CATS = ("ELECTRONICS", "FASHION", "HOME", "BEAUTY", "GROCERY")

CAT_SYNONYMS = {
    "ELECTRONICS": ("electronic", "electronics", "headphone", "headphones", "earbuds", "earphone",
                    "laptop", "phone", "tv", "television", "charger", "cable", "speaker", "camera", "tablet"),
    "FASHION": ("fashion", "apparel", "clothing", "shirt", "t-shirt", "dress", "jeans", "pant",
                "jacket", "shoe", "shoes", "sneaker", "sneakers", "skirt"),
    "BEAUTY": ("beauty", "cosmetic", "cream", "lipstick", "perfume", "lotion", "skincare", "serum"),
    "GROCERY": ("grocery", "food", "coffee", "tea", "snack", "rice", "flour", "beverage"),
    "HOME": ("home", "furniture", "sofa", "chair", "table", "bed", "lamp", "curtain", "desk")
}

PROCEDURE_RE = ("policy", "how do i", "how can i", "what is the", "what's the", "how long",
                "how does", "do you", "does the", "are there", "who is", "can someone", "is there")

INTENTS_FALLBACK = ("order_status", "return_eligibility", "refund", "raise_return",
                    "warranty", "policy_fact", "multi_step", "what_if", "general")

def extract(question: str) -> dict:
    q = question.lower()
    order_id = ORDER_RE.search(question)
    sku = SKU_RE.search(question)

    # 1. Category extraction (exact category name or domain keywords)
    category = next((c for c in CATS if c.lower() in q), None)
    if not category:
        for cat, syns in CAT_SYNONYMS.items():
            if any(re.search(r"\b" + re.escape(s) + r"\b", q) for s in syns):
                category = cat
                break

    # 2. Entity extractions for what-if and multi-step
    days_m = re.search(r"(?:after|in|within|past)\s+(\d+)\s*(?:calendar\s*)?days|(\d+)\s*days\s+(?:ago|after|later)", q)
    days_offset = int(days_m.group(1) or days_m.group(2)) if days_m else None

    tier_m = re.search(r"\b(gold|platinum|standard)\b", q)
    what_if_tier = tier_m.group(1).upper() if tier_m else None

    has_order = bool(order_id)
    return_words = any(w in q for w in ("return", "send back", "give back", "exchange"))
    refund_words = any(w in q for w in ("refund", "money back", "how much", "get back", "reimburse"))
    warranty_words = "warranty" in q or "guarantee" in q or "stopped working" in q or "defective" in q
    general_asking = any(q.startswith(p) or f" {p} " in q for p in PROCEDURE_RE)
    personal_indicators = any(p in q for p in ("my ", "my order", "i bought", "i have", "mine", "my item", "i return my"))

    is_what_if = "what if" in q or "suppose" in q or "hypothetically" in q or "what would happen if" in q
    is_multi_step = (
        ("stopped working" in q and ("return" in q or "what can i do" in q)) or
        ("and if not" in q) or
        ("what can i do" in q and (return_words or warranty_words)) or
        (return_words and warranty_words and not has_order)
    )

    if is_multi_step:
        intent = "multi_step"
    elif is_what_if:
        intent = "what_if"
    elif has_order:
        # personal question about a specific order - deterministic tool intent
        if any(w in q for w in ("raise", "initiate", "file a return", "process my return")):
            intent = "raise_return"
        elif warranty_words and not (return_words or refund_words):
            intent = "warranty"
        elif refund_words or return_words:
            if refund_words and ("refund" in q or "how much" in q):
                intent = "refund"
            elif return_words and not refund_words:
                intent = "return_eligibility"
            else:
                intent = "refund"
        else:
            intent = "order_status"
    else:
        # No order ID in question
        if personal_indicators and (return_words or refund_words):
            intent = "return_eligibility"     # personal without order id -> clarification or sign-in
        elif general_asking or "deliver" in q or "shipping" in q or "window" in q or category or ("return" in q and not personal_indicators):
            intent = "policy_fact"
        elif warranty_words:
            intent = "policy_fact" if ("claim" in q or "how" in q or not personal_indicators) else "warranty"
        else:
            intent = "general"

    return {
        "intent": intent,
        "order_id": order_id.group(0) if order_id else None,
        "sku": sku.group(0) if sku else None,
        "category": category,
        "days_offset": days_offset,
        "what_if_tier": what_if_tier
    }

def route(question: str, llm_classify=None) -> dict:
    """Supervisor router: Regex first, entity extraction, LLM fallback only when intent == general."""
    result = extract(question)
    if result["intent"] == "general" and llm_classify is not None:
        try:
            classified = llm_classify(question)
            if classified.get("intent") in INTENTS_FALLBACK:
                result.update(classified)
        except Exception:
            pass
    return result
