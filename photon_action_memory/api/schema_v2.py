"""Action Context Firewall schema — v0.2.

All models accept unknown optional fields (extra="allow") so agents can attach
shadow-mode metadata without breaking validation across minor schema revisions.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from photon_action_memory.api.schema import (
    AgentInfo,
    RepoInfo,
    SidecarModel,
    TaskState,
    WorkingMemory,
)

SchemaVersionV2 = Literal["action-memory.v0.2"]
DEFAULT_SCHEMA_VERSION_V2: SchemaVersionV2 = "action-memory.v0.2"

ChunkKind = Literal[
    "repo_search",
    "file_inspection",
    "failure_reproduction",
    "edit_attempt",
    "test_verification",
    "answer_prep",
    "other",
]
ChunkOutcome = Literal["useful", "failed", "partial", "irrelevant", "unknown"]
RiskLevel = Literal["low", "medium", "high"]
SummaryLevel = Literal["turn", "chunk", "session", "case"]
AdmissionDecision = Literal["admit", "omit", "expand", "defer", "deny"]
ExpandPolicy = Literal["on_demand_only", "always", "deny"]
StalenessStatusKind = Literal["valid", "stale", "partial", "contradicted", "unknown"]
ValidityStatusKind = Literal["valid", "stale", "partial", "contradicted"]
ContextPackMode = Literal["summary_only", "summary_plus_evidence", "none"]
HypothesisStatus = Literal["open", "confirmed", "rejected"]


# ---------------------------------------------------------------------------
# Shared sub-models
# ---------------------------------------------------------------------------


class StalenessStatus(SidecarModel):
    """Staleness state of a summary or evidence reference."""

    status: StalenessStatusKind | str = "unknown"
    reason: str | None = None


class Locator(SidecarModel):
    """Pointer to a specific file location or command."""

    file: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    command: str | None = None


class AdmissionPolicy(SidecarModel):
    """Admission policy applied when packing context."""

    raw_evidence_policy: str | None = None
    detail_level: str | None = None


class TokenBudget(SidecarModel):
    """Token accounting for a ContextPack."""

    max_tokens: int = Field(ge=0)
    estimated_tokens: int = Field(ge=0)
    tokens_saved_vs_raw: int | None = None


# ---------------------------------------------------------------------------
# ActionChunk
# ---------------------------------------------------------------------------


class ActionChunk(SidecarModel):
    """One meaningful action unit composed from one or more raw EventRecords."""

    schema_version: SchemaVersionV2
    chunk_id: str
    session_id: str
    turn_id: str | None = None
    repo_id: str | None = None
    commit: str | None = None
    kind: ChunkKind | str
    event_ids: list[str] = Field(default_factory=list)
    started_at: str | None = None
    ended_at: str | None = None
    summary: str
    outcome: ChunkOutcome | str = "unknown"
    risk: RiskLevel | str | None = None
    redaction_status: str | None = None


# ---------------------------------------------------------------------------
# EvidenceRef
# ---------------------------------------------------------------------------


class EvidenceRef(SidecarModel):
    """Pointer to evidence that can be expanded on demand without embedding full content."""

    schema_version: SchemaVersionV2
    evidence_id: str
    source_event_id: str | None = None
    source_chunk_id: str | None = None
    kind: str
    summary: str
    locator: Locator | None = None
    redaction_status: str | None = None
    expand_policy: ExpandPolicy | str = "on_demand_only"
    max_expand_chars: int | None = None
    staleness: StalenessStatus = Field(default_factory=StalenessStatus)


# ---------------------------------------------------------------------------
# ActionSummary sub-models
# ---------------------------------------------------------------------------


class ActionDone(SidecarModel):
    """One completed (or attempted) action recorded in an ActionSummary."""

    kind: str
    target: str | None = None
    command: str | None = None
    outcome: str
    status: str
    evidence_ids: list[str] = Field(default_factory=list)


class Fact(SidecarModel):
    """Grounded factual claim; must carry at least one evidence_id to be prompt-visible."""

    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class Hypothesis(SidecarModel):
    """Unconfirmed claim; kept separate from facts to prevent hypothesis-as-fact pollution."""

    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    status: HypothesisStatus | str = "open"


class FailedAttempt(SidecarModel):
    """Action that did not succeed; tracked separately to avoid pointless retries."""

    action: str
    outcome: str
    evidence_ids: list[str] = Field(default_factory=list)
    retry_policy: str | None = None


class AvoidGuidance(SidecarModel):
    """Guidance to skip a known-useless action until conditions change."""

    action: str
    reason: str
    valid_until: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class NextHint(SidecarModel):
    """Suggested next action derived from the current summary state."""

    kind: str
    target: str | None = None
    reason: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class TokenCost(SidecarModel):
    """Estimated token savings from using the summary instead of raw events."""

    estimated_summary_tokens: int = Field(ge=0)
    estimated_raw_tokens: int = Field(ge=0)
    tokens_saved_vs_raw: int


class Validity(SidecarModel):
    """Current validity status of an ActionSummary."""

    status: ValidityStatusKind | str = "valid"
    reason: str | None = None


# ---------------------------------------------------------------------------
# ActionSummary
# ---------------------------------------------------------------------------


class ActionSummary(SidecarModel):
    """Core v0.2 schema: structured summary that separates facts, hypotheses,
    failures, and avoid guidance with evidence pointers."""

    schema_version: SchemaVersionV2
    summary_id: str
    session_id: str | None = None
    repo_id: str | None = None
    commit: str | None = None
    task_signature: str | None = None
    summary_level: SummaryLevel | str = "chunk"
    source_chunk_ids: list[str] = Field(default_factory=list)
    actions_done: list[ActionDone] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    failed_attempts: list[FailedAttempt] = Field(default_factory=list)
    avoid: list[AvoidGuidance] = Field(default_factory=list)
    next_hints: list[NextHint] = Field(default_factory=list)
    token_cost: TokenCost | None = None
    validity: Validity = Field(default_factory=Validity)


# ---------------------------------------------------------------------------
# ContextAdmissionDecision
# ---------------------------------------------------------------------------


class ContextAdmissionDecision(SidecarModel):
    """Records whether a memory item was admitted or excluded from a prompt."""

    schema_version: SchemaVersionV2
    decision_id: str
    item_id: str
    item_kind: Literal["action_summary", "evidence_ref", "warning", "raw_event"] | str
    decision: AdmissionDecision | str
    reason: str | None = None
    risk: RiskLevel | str | None = None
    estimated_tokens: int | None = None
    policy: AdmissionPolicy | None = None


# ---------------------------------------------------------------------------
# ContextPack sub-models
# ---------------------------------------------------------------------------


class ContextPackItem(SidecarModel):
    """A memory item admitted into the prompt via a ContextPack."""

    kind: str
    id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    admission_reason: str | None = None


class OmittedItem(SidecarModel):
    """A memory item excluded from the prompt, with the reason recorded."""

    kind: str
    id: str
    reason: str


class ContextPackWarning(SidecarModel):
    """Non-fatal warning attached to a ContextPack."""

    kind: str
    message: str


# ---------------------------------------------------------------------------
# ContextPack
# ---------------------------------------------------------------------------


class ContextPack(SidecarModel):
    """Sole allowed entry point for action memory into an LLM prompt."""

    schema_version: SchemaVersionV2
    request_id: str
    session_id: str | None = None
    repo_id: str | None = None
    mode: ContextPackMode | str = "summary_only"
    items: list[ContextPackItem] = Field(default_factory=list)
    omitted: list[OmittedItem] = Field(default_factory=list)
    warnings: list[ContextPackWarning] = Field(default_factory=list)
    token_budget: TokenBudget


# ---------------------------------------------------------------------------
# SummaryValidationResult
# ---------------------------------------------------------------------------


class SummaryValidationIssue(SidecarModel):
    """A single fidelity or grounding issue found during summary validation."""

    kind: str
    message: str


class SummaryValidationResult(SidecarModel):
    """Result of validating one ActionSummary against its source evidence."""

    summary_id: str
    status: Literal["valid", "invalid", "partial"] | str
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    issues: list[SummaryValidationIssue] = Field(default_factory=list)
    checked_at: str | None = None


# ---------------------------------------------------------------------------
# POST /v1/context/pack
# ---------------------------------------------------------------------------


class ContextPackBudget(SidecarModel):
    """Budget constraints for context pack generation."""

    max_memory_tokens: int = Field(default=800, ge=0)
    max_evidence_chars: int = Field(default=1200, ge=0)
    raw_evidence_policy: str | None = None
    detail_level: str | None = None


class ContextPackRequest(SidecarModel):
    """Request body for POST /v1/context/pack."""

    schema_version: SchemaVersionV2
    request_id: str
    agent: AgentInfo
    repo: RepoInfo
    task: TaskState
    working_memory: WorkingMemory
    recent_event_ids: list[str] = Field(default_factory=list)
    candidate_summary_ids: list[str] = Field(default_factory=list)
    budget: ContextPackBudget = Field(default_factory=ContextPackBudget)


class ContextPackResponse(SidecarModel):
    """Response body for POST /v1/context/pack."""

    schema_version: SchemaVersionV2
    request_id: str
    model_version: str
    sidecar_status: str
    context_pack: ContextPack
    admission_decisions: list[ContextAdmissionDecision] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# POST /v1/evidence/expand
# ---------------------------------------------------------------------------


class EvidenceExpandBudget(SidecarModel):
    """Budget constraints for evidence expansion."""

    max_chars_per_evidence: int = Field(default=1200, ge=0)
    max_total_chars: int | None = None


class EvidenceExpandPolicy(SidecarModel):
    """Policy governing what can be returned during evidence expansion."""

    redact_again: bool = True
    allow_raw_full_output: bool = False
    allow_selected_snippet: bool = True


class EvidenceExpandRequest(SidecarModel):
    """Request body for POST /v1/evidence/expand."""

    schema_version: SchemaVersionV2
    request_id: str
    evidence_ids: list[str]
    reason: str | None = None
    budget: EvidenceExpandBudget = Field(default_factory=EvidenceExpandBudget)
    policy: EvidenceExpandPolicy = Field(default_factory=EvidenceExpandPolicy)


class ExpandedEvidence(SidecarModel):
    """One expanded evidence item returned by the Evidence Expander."""

    evidence_id: str
    kind: str
    summary: str
    snippet: str | None = None
    locator: Locator | None = None
    redaction_status: str | None = None
    truncated: bool = False


class OmittedEvidence(SidecarModel):
    """Evidence that was requested but not returned, with the reason."""

    evidence_id: str
    reason: str


class EvidenceExpandResponse(SidecarModel):
    """Response body for POST /v1/evidence/expand."""

    schema_version: SchemaVersionV2
    request_id: str
    expanded: list[ExpandedEvidence] = Field(default_factory=list)
    omitted: list[OmittedEvidence] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# POST /v1/summary/validate
# ---------------------------------------------------------------------------


class SummaryValidateRequest(SidecarModel):
    """Request body for POST /v1/summary/validate."""

    schema_version: SchemaVersionV2
    request_id: str
    summary_ids: list[str]
    checks: list[str] = Field(default_factory=list)


class SummaryValidateResponse(SidecarModel):
    """Response body for POST /v1/summary/validate."""

    schema_version: SchemaVersionV2
    request_id: str
    results: list[SummaryValidationResult] = Field(default_factory=list)


__all__ = [
    "DEFAULT_SCHEMA_VERSION_V2",
    "ActionChunk",
    "ActionDone",
    "ActionSummary",
    "AdmissionDecision",
    "AdmissionPolicy",
    "AvoidGuidance",
    "ChunkKind",
    "ChunkOutcome",
    "ContextAdmissionDecision",
    "ContextPack",
    "ContextPackBudget",
    "ContextPackItem",
    "ContextPackMode",
    "ContextPackRequest",
    "ContextPackResponse",
    "ContextPackWarning",
    "EvidenceExpandBudget",
    "EvidenceExpandPolicy",
    "EvidenceExpandRequest",
    "EvidenceExpandResponse",
    "EvidenceRef",
    "ExpandedEvidence",
    "ExpandPolicy",
    "Fact",
    "FailedAttempt",
    "Hypothesis",
    "HypothesisStatus",
    "Locator",
    "NextHint",
    "OmittedEvidence",
    "OmittedItem",
    "RiskLevel",
    "SchemaVersionV2",
    "StalenessStatus",
    "StalenessStatusKind",
    "SummaryLevel",
    "SummaryValidateRequest",
    "SummaryValidateResponse",
    "SummaryValidationIssue",
    "SummaryValidationResult",
    "TokenBudget",
    "TokenCost",
    "Validity",
    "ValidityStatusKind",
]
