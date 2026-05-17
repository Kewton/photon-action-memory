"""Issue #126 — ``action-memory-feedback.v1`` JSONL exporter.

The exporter joins ``summary_feedback`` aggregates with
``context_pack_ranking_log`` rows and emits the records consumed by the v2
checkpoint builder. Each emitted record is a small JSON object with
identifiers, a signed weight, an outcome family, and a source label — no
raw text, no prompt content.

The export is also responsible for producing a ``manifest.source`` block so
the checkpoint builder can later populate ``manifest.source.feedback_max_updated_at``.
Live ``/v1/context/pack`` ranking uses that timestamp to filter out feedback
already baked into the checkpoint, which is what stops the double counting
called out in the Acceptance Criteria.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import IO

from photon_action_memory.eval.ranking_log import (
    LABEL_ADOPTED_FAILURE,
    LABEL_ADOPTED_SAFETY,
    LABEL_ADOPTED_SUCCESS,
    LABEL_IGNORED,
    LABEL_NOT_SELECTED,
    LABEL_OMITTED_BY_GATE,
    LABEL_PARTIAL,
    OutcomeFamily,
    RankingLogStore,
    StoredRankingLogEntry,
)

FEEDBACK_EXPORT_SCHEMA = "action-memory-feedback.v1"

# Weight contributions per source label. ``partial`` is signed by the
# resolved outcome_family so a partial-adoption that still led to safety
# violation lands as a negative weight, while a partial-adoption that
# resolved to success contributes a small positive weight. Ignored and
# not_selected stay as weak negatives; omitted_by_gate is reported as a
# zero-weight gate regression record (the builder routes those to
# ``suppressed_ids`` rather than to a numeric weight).
_BASE_WEIGHTS: dict[str, float] = {
    LABEL_ADOPTED_SUCCESS: 0.25,
    LABEL_ADOPTED_FAILURE: -0.20,
    LABEL_ADOPTED_SAFETY: -1.0,
    LABEL_IGNORED: -0.05,
    LABEL_NOT_SELECTED: -0.02,
    LABEL_PARTIAL: 0.05,
    LABEL_OMITTED_BY_GATE: 0.0,
}

_KIND_TO_BUCKET: dict[str, str] = {
    "action_summary": "summary_weights",
    "summary": "summary_weights",
    "evidence": "evidence_weights",
    "next_action": "next_action_weights",
    "next_hint": "next_action_weights",
    "file": "file_weights",
    "avoid": "avoid_weights",
    "failed_attempt": "avoid_weights",
}


@dataclass(frozen=True)
class FeedbackExportRecord:
    """One JSONL record in the ``action-memory-feedback.v1`` export."""

    schema: str
    kind: str
    bucket: str
    key: str
    weight: float
    outcome_family: OutcomeFamily
    source_label: str
    count: int
    safety_violation: bool
    context_pack_request_id: str | None = None


@dataclass
class FeedbackExportResult:
    """Materialised export ready to be written to JSONL or fed to the builder."""

    records: list[FeedbackExportRecord] = field(default_factory=list)
    feedback_max_updated_at: str | None = None
    record_count: int = 0
    safety_violation_count: int = 0
    label_counts: dict[str, int] = field(default_factory=dict)

    def manifest_source(self) -> dict[str, object]:
        """Return the ``manifest.source`` block for the checkpoint builder."""
        return {
            "schema": FEEDBACK_EXPORT_SCHEMA,
            "feedback_max_updated_at": self.feedback_max_updated_at,
            "feedback_record_count": self.record_count,
            "safety_violation_count": self.safety_violation_count,
            "label_counts": dict(self.label_counts),
        }


def export_action_memory_feedback(
    ranking_log: RankingLogStore,
    *,
    context_pack_request_id: str | None = None,
) -> FeedbackExportResult:
    """Build an export result from the ranking log table.

    The ranking log is the authoritative source for Phase 1 labels: it has
    one row per ``(context_pack_request_id, summary_id, kind)`` with the
    selected flag, omitted_reason, and post-evaluate ``outcome_family``
    already filled in. The exporter classifies each row into one of the
    Phase 1 labels and emits a JSONL record per row.
    """
    entries = ranking_log.iter_entries(context_pack_request_id=context_pack_request_id)
    return build_export_result(entries)


def build_export_result(
    entries: Iterable[StoredRankingLogEntry],
) -> FeedbackExportResult:
    """Build a :class:`FeedbackExportResult` from a sequence of entries."""
    result = FeedbackExportResult()
    for entry in entries:
        record = _record_for(entry)
        if record is None:
            continue
        result.records.append(record)
        result.record_count += 1
        if record.safety_violation:
            result.safety_violation_count += 1
        result.label_counts[record.source_label] = (
            result.label_counts.get(record.source_label, 0) + 1
        )
        if (
            entry.created_at is not None
            and entry.created_at != ""
            and (
                result.feedback_max_updated_at is None
                or entry.created_at > result.feedback_max_updated_at
            )
        ):
            result.feedback_max_updated_at = entry.created_at
    return result


def write_export_jsonl(
    result: FeedbackExportResult,
    path: str | Path | IO[str],
) -> None:
    """Write the export to a JSONL file. The first line is the manifest header."""
    if hasattr(path, "write"):
        _write_to_stream(result, path)  # type: ignore[arg-type]
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        _write_to_stream(result, handle)


def iter_export_jsonl(
    result: FeedbackExportResult,
) -> Iterator[str]:
    """Yield JSONL lines (header + records) without materialising the file."""
    yield json.dumps(
        {"schema": FEEDBACK_EXPORT_SCHEMA, "source": result.manifest_source()},
        sort_keys=True,
    )
    for record in result.records:
        yield json.dumps(asdict(record), sort_keys=True)


def _write_to_stream(result: FeedbackExportResult, handle: IO[str]) -> None:
    for line in iter_export_jsonl(result):
        handle.write(line + "\n")


def _record_for(entry: StoredRankingLogEntry) -> FeedbackExportRecord | None:
    bucket = _KIND_TO_BUCKET.get(entry.kind)
    if bucket is None:
        return None
    label = entry.label()
    outcome_family: OutcomeFamily = entry.outcome_family or "unknown"
    safety_violation = label == LABEL_ADOPTED_SAFETY or outcome_family == "safety"
    weight = _signed_weight(label=label, outcome_family=outcome_family)
    return FeedbackExportRecord(
        schema=FEEDBACK_EXPORT_SCHEMA,
        kind=entry.kind,
        bucket=bucket,
        key=entry.summary_id,
        weight=weight,
        outcome_family=outcome_family,
        source_label=label,
        count=1,
        safety_violation=safety_violation,
        context_pack_request_id=entry.context_pack_request_id,
    )


def _signed_weight(*, label: str, outcome_family: OutcomeFamily) -> float:
    base = _BASE_WEIGHTS.get(label, 0.0)
    if label != LABEL_PARTIAL:
        return round(base, 4)
    # Partial adoption — sign by outcome_family so success-leaning partials
    # are positive, failure-leaning partials are negative, safety partials
    # turn into a strong negative penalty, and unknown stays neutral-low.
    if outcome_family == "success":
        return round(base, 4)
    if outcome_family == "failure":
        return round(-base, 4)
    if outcome_family == "safety":
        return -0.5
    return 0.0


__all__ = [
    "FEEDBACK_EXPORT_SCHEMA",
    "FeedbackExportRecord",
    "FeedbackExportResult",
    "build_export_result",
    "export_action_memory_feedback",
    "iter_export_jsonl",
    "write_export_jsonl",
]
