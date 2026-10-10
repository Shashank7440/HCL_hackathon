from typing import Any, TypedDict

class AgentState(TypedDict, total=False):
    trace_id: str
    question: str
    as_of_date: str
    customer_id: str | None          # header identity only
    intent: str
    order_id: str | None
    sku: str | None
    category: str | None
    days_offset: int | None
    what_if_tier: str | None
    plan: list[str] | None
    answer: str
    answer_type: str
    citations: list[dict]
    tools_invoked: list[dict]
    applied_rules: list[dict]
    conflicts_detected: list[dict]
    upcoming_changes: list[dict]
    assumptions: list[str]
    explanation: str
    refused: bool
    llm_calls: int
    tokens: int
    errors: list[str]
    extra: dict[str, Any]
