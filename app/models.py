"""Shared data contracts (Pydantic v2).

This file is the agreement between team members: every module passes
these objects to the others. Change a field here only after telling the
team, because several modules depend on each one.

The request/response shapes follow the hackathon brief, section 6 and
Annexes B-D.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AnswerType(str, Enum):
    """The six answer types allowed by the brief (section 6.2)."""

    retrieved_fact = "retrieved_fact"
    calculated = "calculated"
    not_found = "not_found"
    clarification_needed = "clarification_needed"
    refused = "refused"
    conflict_flagged = "conflict_flagged"


# ---------------------------------------------------------------- /ask --
class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    as_of_date: date | None = None  # defaults to today in the API


class Citation(BaseModel):
    doc_id: str
    title: str
    section: str | None = None
    page: int | None = None
    version: str | None = None
    effective_from: date | None = None


class ToolCall(BaseModel):
    tool: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)


class AppliedRule(BaseModel):
    rule_id: str
    value: str
    source_doc_id: str


class Conflict(BaseModel):
    kept: str
    discarded: str
    reason: str
    step: int


class AskResponse(BaseModel):
    trace_id: str
    answer: str
    answer_type: AnswerType
    citations: list[Citation] = Field(default_factory=list)
    tools_invoked: list[ToolCall] = Field(default_factory=list)
    applied_rules: list[AppliedRule] = Field(default_factory=list)
    conflicts_detected: list[Conflict] = Field(default_factory=list)
    explanation: str = ""
    as_of_date: date
    upcoming_changes: list[Citation] = Field(default_factory=list)


# ------------------------------------------------------------- /ingest --
class SourceMetadata(BaseModel):
    """One row of the Source Register (Annex B); also the /ingest metadata."""

    doc_id: str
    title: str
    issuer: str
    authority_level: int = Field(ge=1, le=5)
    doc_type: str
    version: str
    effective_from: date
    effective_to: date | None = None
    supersedes: str = ""  # "DOC-ID" or "DOC-ID#clause", ';'-separated
    scope_programmes: str = "ALL"
    scope_batches: str = "ALL"
    provenance: str
    retrieved_on: date | None = None
    synthetic: str = Field(default="N", pattern="^[YN]$")


class IngestResponse(BaseModel):
    doc_id: str
    chunks_indexed: int
    status: str
    rules_added: int = 0


# ------------------------------------------------- internal contracts --
class Hit(BaseModel):
    """One retrieved chunk plus its metadata and precedence status."""

    chunk_id: str
    doc_id: str
    text: str
    score: float
    section: str | None = None
    page: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = "applicable"  # applicable | superseded | upcoming | lower_authority


class Rule(BaseModel):
    """One row of the rule registry (Annex C)."""

    rule_id: str
    description: str
    parameter: str
    operator: str
    value: str
    scope_programmes: str = "ALL"
    scope_batches: str = "ALL"
    effective_from: date
    effective_to: date | None = None
    source_doc_id: str
    source_section: str


class ToolResult(BaseModel):
    """What every deterministic tool returns."""

    tool: str
    ok: bool = True
    data: dict[str, Any] = Field(default_factory=dict)
    rule_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    error: str | None = None


class Decision(BaseModel):
    """Output of the precedence engine (Annex A)."""

    winner: str | None = None
    discarded: list[Conflict] = Field(default_factory=list)
    upcoming: list[str] = Field(default_factory=list)
    unresolved: bool = False
