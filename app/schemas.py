"""Pydantic v2 models == APIcontract.md. Single source of truth for every response shape."""
from datetime import date
from typing import Any, Literal
from pydantic import BaseModel, Field

class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    as_of_date: date | None = None
    customer_id: str | None = None

class Citation(BaseModel):
    doc_id: str = ""
    title: str = ""
    section: str = ""
    page: int = 1
    version: str = ""
    effective_from: str = ""

class ToolInvoked(BaseModel):
    tool: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)

class AppliedRule(BaseModel):
    rule_id: str
    value: str
    source_doc_id: str = ""

class ConflictDetected(BaseModel):
    parameter: str
    winner: str
    resolution: list[str] = Field(default_factory=list)

class UpcomingChange(BaseModel):
    parameter: str = ""
    rule_id: str = ""
    value: str = ""
    effective_from: str = ""
    source_doc_id: str = ""

AnswerType = Literal["retrieved_fact", "calculated", "not_found",
                     "clarification_needed", "refused", "conflict_flagged"]

class AskResponse(BaseModel):
    trace_id: str
    answer: str
    answer_type: AnswerType
    citations: list[Citation] = Field(default_factory=list)
    tools_invoked: list[ToolInvoked] = Field(default_factory=list)
    applied_rules: list[AppliedRule] = Field(default_factory=list)
    conflicts_detected: list[ConflictDetected] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    explanation: str = ""
    as_of_date: str
    upcoming_changes: list[UpcomingChange] = Field(default_factory=list)

class IngestResponse(BaseModel):
    doc_id: str
    chunks_indexed: int
    status: str
    rules_upserted: int

class SourceDoc(BaseModel):
    doc_id: str
    title: str
    issuer: str = ""
    authority_level: int
    doc_type: str = ""
    version: str
    effective_from: str
    effective_to: str = ""
    supersedes: str = ""
    scope_categories: str = "ALL"
    scope_tiers: str = "ALL"
    provenance: str = ""
    retrieved_on: str = ""
    synthetic: str = "N"
    chunks_indexed: int = 0

class AuditResponse(BaseModel):
    trace_id: str
    timestamp: str = ""
    customer_id: str | None = None
    record: dict[str, Any] = Field(default_factory=dict)

class ErrorBody(BaseModel):
    code: str
    message: str
    detail: Any = None

class ErrorEnvelope(BaseModel):
    error: ErrorBody
