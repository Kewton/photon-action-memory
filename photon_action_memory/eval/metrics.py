"""Aggregate metrics for offline and shadow-mode evaluation fixtures."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from math import ceil
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

REPORT_SCHEMA_VERSION = "eval-metrics.v1"


class EvalModel(BaseModel):
    """Base model for normalized eval fixture records."""

    model_config = ConfigDict(extra="ignore")


class EvalAction(EvalModel):
    """Normalized action shape used for matching suggestions to observed actions."""

    kind: str
    target: str | None = None
    command: str | None = None
    query: str | None = None


class EvalWarning(EvalModel):
    """Normalized warning emitted by the sidecar."""

    kind: str


class EvalSuggestion(EvalAction):
    """Suggestion candidate in a normalized shadow fixture."""

    evidence_ids: list[str] = Field(default_factory=list)


class ShadowEvalRecord(EvalModel):
    """Single normalized shadow evaluation record.

    This is intentionally not a raw log schema. Free-form prompts, tool output,
    and event summaries are ignored by validation and are never included in
    reports.
    """

    suggestions: list[EvalSuggestion] = Field(default_factory=list)
    actual_next_action: EvalAction | None = None
    actual_target_file: str | None = None
    useful_evidence_ids: list[str] = Field(default_factory=list)
    warnings: list[EvalWarning] = Field(default_factory=list)
    repeated_exploration_occurred: bool = False
    outcome: str | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    sidecar_status: str = "ok"
    fail_open: bool = False


class MetricsReport(BaseModel):
    """Commit-friendly aggregate eval summary."""

    schema_version: Literal["eval-metrics.v1"] = "eval-metrics.v1"
    total_records: int
    next_action_top_k: int
    evaluated_next_action_records: int
    next_action_hits: int
    next_action_top_k_accuracy: float
    evaluated_target_file_records: int
    target_file_hits: int
    target_file_hit_rate: float
    evaluated_useful_evidence_records: int
    useful_evidence_hits: int
    useful_evidence_hit_rate: float
    repeated_exploration_warnings: int
    repeated_exploration_warning_true_positives: int
    repeated_exploration_warning_precision: float
    fail_open_incident_count: int
    latency_sample_count: int
    suggest_latency_p50_ms: float | None
    suggest_latency_p95_ms: float | None
    sidecar_status_counts: dict[str, int]
    outcome_counts: dict[str, int]


RawRecord = ShadowEvalRecord | Mapping[str, Any]


def build_metrics_report(records: Sequence[RawRecord], *, top_k: int = 3) -> MetricsReport:
    """Build an aggregate metrics report from normalized shadow records."""
    if top_k < 1:
        raise ValueError("top_k must be at least 1")

    parsed = [_coerce_record(record) for record in records]

    next_action_records = [record for record in parsed if record.actual_next_action is not None]
    next_action_hits = sum(
        _has_action_hit(record, top_k=top_k) for record in next_action_records
    )

    target_file_records = [record for record in parsed if _actual_target_file(record)]
    target_file_hits = sum(
        _has_target_file_hit(record, top_k=top_k) for record in target_file_records
    )

    useful_evidence_records = [record for record in parsed if record.useful_evidence_ids]
    useful_evidence_hits = sum(
        _has_useful_evidence_hit(record, top_k=top_k) for record in useful_evidence_records
    )

    repeated_warning_records = [
        record for record in parsed if _has_repeated_exploration_warning(record)
    ]
    repeated_warning_true_positives = sum(
        record.repeated_exploration_occurred for record in repeated_warning_records
    )

    latencies = sorted(record.latency_ms for record in parsed if record.latency_ms is not None)

    return MetricsReport(
        total_records=len(parsed),
        next_action_top_k=top_k,
        evaluated_next_action_records=len(next_action_records),
        next_action_hits=next_action_hits,
        next_action_top_k_accuracy=_rate(next_action_hits, len(next_action_records)),
        evaluated_target_file_records=len(target_file_records),
        target_file_hits=target_file_hits,
        target_file_hit_rate=_rate(target_file_hits, len(target_file_records)),
        evaluated_useful_evidence_records=len(useful_evidence_records),
        useful_evidence_hits=useful_evidence_hits,
        useful_evidence_hit_rate=_rate(useful_evidence_hits, len(useful_evidence_records)),
        repeated_exploration_warnings=len(repeated_warning_records),
        repeated_exploration_warning_true_positives=repeated_warning_true_positives,
        repeated_exploration_warning_precision=_rate(
            repeated_warning_true_positives, len(repeated_warning_records)
        ),
        fail_open_incident_count=sum(_is_fail_open_incident(record) for record in parsed),
        latency_sample_count=len(latencies),
        suggest_latency_p50_ms=_percentile(latencies, 50),
        suggest_latency_p95_ms=_percentile(latencies, 95),
        sidecar_status_counts=_count_values(record.sidecar_status for record in parsed),
        outcome_counts=_count_values(record.outcome or "unknown" for record in parsed),
    )


def _coerce_record(record: RawRecord) -> ShadowEvalRecord:
    if isinstance(record, ShadowEvalRecord):
        return record
    return ShadowEvalRecord.model_validate(record)


def _has_action_hit(record: ShadowEvalRecord, *, top_k: int) -> bool:
    actual = record.actual_next_action
    if actual is None:
        return False
    return any(_action_matches(suggestion, actual) for suggestion in record.suggestions[:top_k])


def _action_matches(suggestion: EvalAction, actual: EvalAction) -> bool:
    if suggestion.kind != actual.kind:
        return False

    for field_name in ("target", "command", "query"):
        actual_value = getattr(actual, field_name)
        suggestion_value = getattr(suggestion, field_name)
        if actual_value and suggestion_value != actual_value:
            return False

    return True


def _actual_target_file(record: ShadowEvalRecord) -> str | None:
    if record.actual_target_file:
        return record.actual_target_file
    if record.actual_next_action is None:
        return None
    return record.actual_next_action.target


def _has_target_file_hit(record: ShadowEvalRecord, *, top_k: int) -> bool:
    target_file = _actual_target_file(record)
    if target_file is None:
        return False
    return any(suggestion.target == target_file for suggestion in record.suggestions[:top_k])


def _has_useful_evidence_hit(record: ShadowEvalRecord, *, top_k: int) -> bool:
    useful_evidence = set(record.useful_evidence_ids)
    suggested_evidence = {
        evidence_id
        for suggestion in record.suggestions[:top_k]
        for evidence_id in suggestion.evidence_ids
    }
    return bool(useful_evidence & suggested_evidence)


def _has_repeated_exploration_warning(record: ShadowEvalRecord) -> bool:
    repeated_warning_kinds = {"repeat_failure", "repeated_exploration"}
    return any(warning.kind in repeated_warning_kinds for warning in record.warnings)


def _is_fail_open_incident(record: ShadowEvalRecord) -> bool:
    if record.fail_open:
        return True
    return record.sidecar_status in {"error", "failed", "timeout", "unavailable"}


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _percentile(sorted_values: Sequence[float], percentile: int) -> float | None:
    if not sorted_values:
        return None
    index = max(0, ceil((percentile / 100) * len(sorted_values)) - 1)
    return sorted_values[index]


def _count_values(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


__all__ = [
    "EvalAction",
    "EvalSuggestion",
    "EvalWarning",
    "MetricsReport",
    "REPORT_SCHEMA_VERSION",
    "ShadowEvalRecord",
    "build_metrics_report",
]
