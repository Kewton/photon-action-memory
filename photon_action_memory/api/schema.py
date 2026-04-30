"""Versioned sidecar API schema.

The v1 schema intentionally accepts unknown optional fields so agents can add
shadow-mode metadata without breaking older sidecar builds.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from photon_action_memory import SCHEMA_VERSION

SchemaVersion = Literal["action-memory.v1"]
DEFAULT_SCHEMA_VERSION: SchemaVersion = "action-memory.v1"
FALLBACK_MODEL_VERSION = "photon-action-memory-v0.1.0-fallback"

ActionKind = Literal[
    "read",
    "search",
    "edit",
    "test",
    "build",
    "inspect",
    "ask_user",
    "answer",
    "replan",
]
WarningKind = Literal[
    "drift",
    "repeat_failure",
    "missing_evidence",
    "sidecar_unavailable",
    "model_unavailable",
]
SidecarStatus = Literal["ok", "timeout", "error", "unavailable", "not_called"]
ShadowOutcome = Literal["success", "failure", "partial", "unknown"]


class SidecarModel(BaseModel):
    """Base model for forward-compatible sidecar DTOs."""

    model_config = ConfigDict(extra="allow")


class AgentInfo(SidecarModel):
    """Agent identity included in sidecar requests."""

    name: str
    version: str | None = None


class RepoInfo(SidecarModel):
    """Repository state visible to the coding agent."""

    root: str
    name: str | None = None
    branch: str | None = None
    commit: str | None = None


class TaskState(SidecarModel):
    """Current user task and agent mode."""

    user_request: str
    mode: Literal["plan", "act", "answer"] | str
    summary: str | None = None


class WorkingMemory(SidecarModel):
    """Neutral representation of agent working memory, including Anvil-like L2 state."""

    active_task: str | None = None
    constraints: list[str] = Field(default_factory=list)
    touched_files: list[str] = Field(default_factory=list)
    unresolved_errors: list[str] = Field(default_factory=list)
    active_precautions: list[str] = Field(default_factory=list)
    plan: list[str] = Field(default_factory=list)
    completed_steps: list[str] = Field(default_factory=list)
    pending_steps: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class RecentEvent(SidecarModel):
    """Compact event embedded in a suggest request."""

    type: str
    tool: str | None = None
    status: str | None = None
    summary: str
    event_id: str | None = None
    evidence_id: str | None = None


class Budget(SidecarModel):
    """Suggestion budget hints for the sidecar."""

    max_suggestions: int = Field(default=8, ge=0)
    max_evidence_chars: int = Field(default=4000, ge=0)


class SuggestRequest(SidecarModel):
    """Request body for `POST /v1/suggest`."""

    schema_version: SchemaVersion
    request_id: str
    agent: AgentInfo
    repo: RepoInfo
    task: TaskState
    working_memory: WorkingMemory
    recent_events: list[RecentEvent] = Field(default_factory=list)
    budget: Budget = Field(default_factory=Budget)


class Suggestion(SidecarModel):
    """Action guidance returned by the sidecar."""

    id: str | None = None
    kind: ActionKind
    target: str | None = None
    command: str | None = None
    query: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)
    risk: str | None = None


class Evidence(SidecarModel):
    """Evidence item supporting one or more suggestions."""

    id: str
    kind: str
    summary: str
    source: str | None = None


class Warning(SidecarModel):
    """Non-fatal sidecar warning."""

    kind: WarningKind | str
    message: str


class SuggestResponse(SidecarModel):
    """Response body for `POST /v1/suggest`."""

    schema_version: SchemaVersion
    request_id: str
    model_version: str
    suggestions: list[Suggestion] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    warnings: list[Warning] = Field(default_factory=list)


class Artifact(SidecarModel):
    """File, command, or tool artifact attached to an event."""

    kind: str
    value: str
    metadata: dict[str, object] = Field(default_factory=dict)


class SidecarEvent(SidecarModel):
    """Event payload accepted by `POST /v1/events`."""

    schema_version: SchemaVersion
    event_id: str
    session_id: str
    turn_id: str | None = None
    repo_id: str | None = None
    timestamp: str
    event_type: str = Field(validation_alias=AliasChoices("event_type", "type"))
    tool_name: str | None = None
    status: str | None = None
    summary: str
    artifacts: list[Artifact] = Field(default_factory=list)
    redaction_status: Literal["raw", "sanitized", "redacted", "unknown"] | str = "unknown"


class EventRequest(SidecarModel):
    """Request body for ingesting one or more events."""

    schema_version: SchemaVersion
    request_id: str
    events: list[SidecarEvent]


class EventResponse(SidecarModel):
    """Response body for `POST /v1/events`."""

    status: str
    event_id: str
    stored: bool


class ActualNextAction(SidecarModel):
    """Action Anvil actually took after receiving shadow-mode suggestions."""

    kind: ActionKind | str
    target: str | None = None
    command: str | None = None
    query: str | None = None
    summary: str


class EvaluationRecord(SidecarModel):
    """One shadow-mode evaluation record for `POST /v1/evaluate`."""

    request_id: str
    suggestion_ids: list[str] = Field(default_factory=list)
    actual_next_action: ActualNextAction
    matched: bool
    ignored_reason: str | None = None
    outcome: ShadowOutcome | str = "unknown"
    latency_ms: float = Field(ge=0)
    sidecar_status: SidecarStatus | str


class EvaluationRequest(SidecarModel):
    """Request body for recording shadow-mode suggestion outcomes."""

    schema_version: SchemaVersion
    request_id: str
    session_id: str | None = None
    records: list[EvaluationRecord]


class EvaluationResponse(SidecarModel):
    """Response body for accepted shadow-mode evaluation records."""

    status: str
    accepted: int = Field(ge=0)


class HealthResponse(SidecarModel):
    """Response body for health checks."""

    status: str
    schema_version: SchemaVersion = DEFAULT_SCHEMA_VERSION


EvidenceItem = Evidence
SuggestBudget = Budget
WarningMessage = Warning


__all__ = [
    "SCHEMA_VERSION",
    "ActionKind",
    "ActualNextAction",
    "AgentInfo",
    "Artifact",
    "Budget",
    "DEFAULT_SCHEMA_VERSION",
    "EventRequest",
    "EventResponse",
    "EvaluationRecord",
    "EvaluationRequest",
    "EvaluationResponse",
    "Evidence",
    "EvidenceItem",
    "FALLBACK_MODEL_VERSION",
    "HealthResponse",
    "RecentEvent",
    "RepoInfo",
    "SchemaVersion",
    "SidecarEvent",
    "SidecarModel",
    "SidecarStatus",
    "ShadowOutcome",
    "SuggestBudget",
    "SuggestRequest",
    "SuggestResponse",
    "Suggestion",
    "TaskState",
    "Warning",
    "WarningKind",
    "WarningMessage",
    "WorkingMemory",
]
