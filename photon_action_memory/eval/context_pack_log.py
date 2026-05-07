"""ContextPack adoption and outcome evaluation logging.

Provides normalized record types and an aggregation function for multi-turn
ContextPack evaluation data collected through POST /v1/evaluate.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CONTEXT_PACK_LOG_SCHEMA = "context-pack-eval.v1"

_SUCCESS_OUTCOMES: frozenset[str] = frozenset({"success", "accepted", "completed"})


class ContextPackEvalRecord(BaseModel):
    """Normalized single-turn record of ContextPack adoption and task outcome."""

    model_config = ConfigDict(extra="ignore")

    context_pack_request_id: str = ""
    adoption_status: str = "adopted"
    ignored_reason: str | None = None
    evidence_expand_requested: bool = False
    evidence_ids_expanded: list[str] = Field(default_factory=list)
    items_adopted_count: int = Field(default=0, ge=0)
    items_ignored_count: int = Field(default=0, ge=0)
    outcome: str | None = None
    latency_ms: float | None = Field(default=None, ge=0)


class ContextPackAdoptionReport(BaseModel):
    """Aggregate ContextPack adoption report across multiple turns."""

    schema_version: Literal["context-pack-eval.v1"] = "context-pack-eval.v1"
    total_turns: int
    adopted_count: int
    ignored_count: int
    partial_count: int
    # Anvil canary/shadow statuses (Anvil Issue #558)
    shadow_not_injected_count: int = 0
    not_available_count: int = 0
    error_count: int = 0
    adoption_rate: float
    evidence_expand_rate: float
    task_success_rate: float
    ignored_reason_counts: dict[str, int]
    outcome_counts: dict[str, int]


RawContextPackEvalRecord = ContextPackEvalRecord | Mapping[str, Any]


def aggregate_context_pack_eval(
    records: Sequence[RawContextPackEvalRecord],
) -> ContextPackAdoptionReport:
    """Build an aggregate adoption report from normalized eval records."""
    parsed = [_coerce(r) for r in records]
    n = len(parsed)

    adopted = sum(1 for r in parsed if r.adoption_status == "adopted")
    ignored = sum(1 for r in parsed if r.adoption_status == "ignored")
    partial = sum(1 for r in parsed if r.adoption_status == "partial")
    shadow_not_injected = sum(1 for r in parsed if r.adoption_status == "shadow_not_injected")
    not_available = sum(1 for r in parsed if r.adoption_status == "not_available")
    error = sum(1 for r in parsed if r.adoption_status == "error")
    expand_used = sum(1 for r in parsed if r.evidence_expand_requested)
    successes = sum(1 for r in parsed if r.outcome in _SUCCESS_OUTCOMES)

    ignored_reasons: dict[str, int] = {}
    for r in parsed:
        if r.adoption_status == "ignored" and r.ignored_reason:
            ignored_reasons[r.ignored_reason] = ignored_reasons.get(r.ignored_reason, 0) + 1

    outcome_counts: dict[str, int] = {}
    for r in parsed:
        key = r.outcome or "unknown"
        outcome_counts[key] = outcome_counts.get(key, 0) + 1

    return ContextPackAdoptionReport(
        total_turns=n,
        adopted_count=adopted,
        ignored_count=ignored,
        partial_count=partial,
        shadow_not_injected_count=shadow_not_injected,
        not_available_count=not_available,
        error_count=error,
        adoption_rate=_rate(adopted + partial, n),
        evidence_expand_rate=_rate(expand_used, n),
        task_success_rate=_rate(successes, n),
        ignored_reason_counts=dict(sorted(ignored_reasons.items())),
        outcome_counts=dict(sorted(outcome_counts.items())),
    )


def _coerce(record: RawContextPackEvalRecord) -> ContextPackEvalRecord:
    if isinstance(record, ContextPackEvalRecord):
        return record
    return ContextPackEvalRecord.model_validate(record)


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


__all__ = [
    "CONTEXT_PACK_LOG_SCHEMA",
    "ContextPackAdoptionReport",
    "ContextPackEvalRecord",
    "RawContextPackEvalRecord",
    "aggregate_context_pack_eval",
]
