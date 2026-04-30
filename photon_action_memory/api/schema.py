"""Versioned sidecar API schema.

These models intentionally keep nested payloads permissive for the M2 sidecar
MVP. Later schema-first work can tighten individual nested objects while
preserving the top-level request/response contract introduced here.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from photon_action_memory import SCHEMA_VERSION

FALLBACK_MODEL_VERSION = "photon-action-memory-v0.1.0-fallback"


class ExtraBaseModel(BaseModel):
    """Base model that accepts forward-compatible optional fields."""

    model_config = ConfigDict(extra="allow")


class WarningMessage(ExtraBaseModel):
    kind: str
    message: str


class EvidenceItem(ExtraBaseModel):
    id: str
    kind: str
    summary: str
    source: str = "request"


class Suggestion(ExtraBaseModel):
    kind: str
    target: str | None = None
    command: str | None = None
    query: str | None = None
    confidence: float
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)


class SuggestBudget(ExtraBaseModel):
    max_suggestions: int = 8
    max_evidence_chars: int = 4000


class SuggestRequest(ExtraBaseModel):
    request_id: str
    schema_version: str = SCHEMA_VERSION
    agent: dict[str, Any] = Field(default_factory=dict)
    repo: dict[str, Any] = Field(default_factory=dict)
    task: dict[str, Any] = Field(default_factory=dict)
    working_memory: dict[str, Any] = Field(default_factory=dict)
    recent_events: list[dict[str, Any]] = Field(default_factory=list)
    budget: SuggestBudget = Field(default_factory=SuggestBudget)


class SuggestResponse(ExtraBaseModel):
    request_id: str
    schema_version: str = SCHEMA_VERSION
    model_version: str
    suggestions: list[Suggestion] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    warnings: list[WarningMessage] = Field(default_factory=list)


class EventRequest(ExtraBaseModel):
    schema_version: str = SCHEMA_VERSION
    event_id: str | None = None
    session_id: str | None = None
    turn_id: str | None = None
    repo_id: str | None = None
    timestamp: str | None = None
    event_type: str = "synthetic"
    tool_name: str | None = None
    status: str | None = None
    summary: str = ""
    artifacts: dict[str, Any] = Field(default_factory=dict)
    redaction_status: str = "unspecified"
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventResponse(ExtraBaseModel):
    status: str
    event_id: str
    stored: bool


class HealthResponse(ExtraBaseModel):
    status: str
    schema_version: str = SCHEMA_VERSION


__all__ = [
    "SCHEMA_VERSION",
    "EventRequest",
    "EventResponse",
    "EvidenceItem",
    "FALLBACK_MODEL_VERSION",
    "HealthResponse",
    "SuggestRequest",
    "SuggestResponse",
    "Suggestion",
    "WarningMessage",
]
