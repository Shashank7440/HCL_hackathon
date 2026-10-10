"""Byte-identical response constants (R3, R7). Never format or localise these."""
NOT_FOUND_MSG = "I could not find this information in the authorised sources."
REFUSAL_MSG = "I can't help with that request for this account."
SIGN_IN_MSG = "Please sign in so I can look up your orders."

ANSWER_TYPES = ("retrieved_fact", "calculated", "not_found",
                "clarification_needed", "refused", "conflict_flagged")

INTENTS = ("order_status", "return_eligibility", "refund", "raise_return",
           "warranty", "policy_fact", "general")

REGISTERED_PARAMETERS = ("return_window_days", "restocking_fee_pct", "reverse_shipping_fee",
                        "auto_refund_limit", "non_returnable", "fee_applicable_reasons")
