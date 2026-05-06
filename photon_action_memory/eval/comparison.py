"""Context Firewall condition comparison metrics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

COMPARISON_REPORT_SCHEMA: str = "comparison-metrics.v1"

# Named evaluation conditions for Context Firewall comparisons (issue #42).
EVAL_CONDITIONS: frozenset[str] = frozenset(
    {
        "no_memory",
        "full_transcript",
        "static_summary_memory",
        "retrieval_memory",
        "photon_summary_only",
        "photon_summary_evidence",
    }
)

_SUCCESS_OUTCOMES: frozenset[str] = frozenset({"success", "accepted", "completed"})


class ComparisonRecord(BaseModel):
    """Normalized record for Context Firewall condition comparison.

    Carries the condition label, retry flag, and optional per-turn pollution
    counts sourced from PollutionRecord measurements (see pollution.py).
    Raw logs, prompts, and tool outputs are intentionally excluded.
    """

    model_config = ConfigDict(extra="ignore")

    condition: str = "no_memory"
    outcome: str | None = None
    repeated_exploration_occurred: bool = False
    failed_action_retry: bool = False
    # Per-turn pollution counts; aggregate from pollution.py PollutionRecord
    duplicate_context_incidents: int = Field(default=0, ge=0)
    ungrounded_fact_incidents: int = Field(default=0, ge=0)
    hypothesis_as_fact_incidents: int = Field(default=0, ge=0)
    total_summaries_evaluated: int = Field(default=0, ge=0)
    total_facts_evaluated: int = Field(default=0, ge=0)


class ConditionSummary(BaseModel):
    """Aggregate metrics for one named eval condition."""

    condition: str
    total_records: int
    task_success_rate: float
    repeated_exploration_rate: float
    failed_action_retry_rate: float
    duplicate_context_rate: float
    ungrounded_fact_rate: float
    hypothesis_as_fact_rate: float


class ComparisonReport(BaseModel):
    """Aggregate-only comparison report across named eval conditions.

    All values are counts or rates.  No raw logs, prompts, or tool outputs
    are included.
    """

    schema_version: Literal["comparison-metrics.v1"] = "comparison-metrics.v1"
    total_records: int
    conditions: list[ConditionSummary]


RawComparisonRecord = ComparisonRecord | Mapping[str, Any]


def build_comparison_report(
    records: Sequence[RawComparisonRecord],
) -> ComparisonReport:
    """Build an aggregate comparison report grouped by condition."""
    parsed = [_coerce(r) for r in records]

    groups: dict[str, list[ComparisonRecord]] = {}
    for record in parsed:
        groups.setdefault(record.condition, []).append(record)

    conditions = [_summarise_condition(cond, group) for cond, group in sorted(groups.items())]
    return ComparisonReport(total_records=len(parsed), conditions=conditions)


def _coerce(record: RawComparisonRecord) -> ComparisonRecord:
    if isinstance(record, ComparisonRecord):
        return record
    return ComparisonRecord.model_validate(record)


def _summarise_condition(condition: str, records: list[ComparisonRecord]) -> ConditionSummary:
    n = len(records)
    successes = sum(1 for r in records if r.outcome in _SUCCESS_OUTCOMES)
    repeated = sum(1 for r in records if r.repeated_exploration_occurred)
    retries = sum(1 for r in records if r.failed_action_retry)
    dup_incidents = sum(r.duplicate_context_incidents for r in records)
    ungrounded = sum(r.ungrounded_fact_incidents for r in records)
    hypothesis = sum(r.hypothesis_as_fact_incidents for r in records)
    total_summaries = sum(r.total_summaries_evaluated for r in records)
    total_facts = sum(r.total_facts_evaluated for r in records)
    return ConditionSummary(
        condition=condition,
        total_records=n,
        task_success_rate=_rate(successes, n),
        repeated_exploration_rate=_rate(repeated, n),
        failed_action_retry_rate=_rate(retries, n),
        duplicate_context_rate=_rate(dup_incidents, total_summaries),
        ungrounded_fact_rate=_rate(ungrounded, total_facts),
        hypothesis_as_fact_rate=_rate(hypothesis, total_facts),
    )


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


__all__ = [
    "COMPARISON_REPORT_SCHEMA",
    "EVAL_CONDITIONS",
    "ComparisonRecord",
    "ComparisonReport",
    "ConditionSummary",
    "RawComparisonRecord",
    "build_comparison_report",
]
