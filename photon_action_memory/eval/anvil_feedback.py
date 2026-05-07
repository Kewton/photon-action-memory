"""Aggregate feedback from Anvil evaluate logs for PHOTON scoring.

Derives quality signals from ContextPackEvalRecord sequences.  fail-open,
error, not_available, and shadow_not_injected turns are excluded from the
quality computation so that infrastructure noise does not pollute signals.

The resulting PackFeedback contains only aggregate counts and rates — no raw
prompts, tool outputs, or user text — making it safe to persist for future
model training feature extraction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from photon_action_memory.eval.context_pack_log import (
    ContextPackEvalRecord,
    RawContextPackEvalRecord,
)

# Statuses that indicate fail-open or infrastructure-error turns.
# These contribute to total_turns but not to quality_turns or quality_score.
EXCLUDED_QUALITY_STATUSES: frozenset[str] = frozenset(
    {
        "error",
        "not_available",
        "shadow_not_injected",
    }
)

_SUCCESS_OUTCOMES: frozenset[str] = frozenset({"success", "accepted", "completed"})


@dataclass(frozen=True)
class EvidenceFeedback:
    """Per-evidence aggregate feedback derived from Anvil evaluate logs.

    expansion_count: total quality-turn expansions of this evidence_id.
    success_count:   expansions that correlated with a success outcome.
    quality_score:   success_count / expansion_count (0.0 if never expanded).

    This is an aggregate-safe feature: it never stores raw event content.
    """

    evidence_id: str
    expansion_count: int
    success_count: int
    quality_score: float


@dataclass(frozen=True)
class PackFeedback:
    """Aggregate pack-level quality signal from Anvil evaluate logs.

    Aggregate-safe features suitable for future model training:
    - total_turns, quality_turns: turncount breakdown (no raw content).
    - adoption_count, success_count, quality_score: adoption/outcome rates.
    - evidence_feedback: per-evidence expansion × outcome correlation.

    fail-open/error/not_available/shadow_not_injected records are counted in
    total_turns but excluded from quality_turns and quality_score.
    """

    total_turns: int
    quality_turns: int
    adoption_count: int
    success_count: int
    quality_score: float
    evidence_feedback: dict[str, EvidenceFeedback]


def aggregate_anvil_feedback(
    records: Sequence[RawContextPackEvalRecord],
) -> PackFeedback:
    """Build aggregate feedback from a sequence of Anvil evaluate log records.

    Records with adoption_status in EXCLUDED_QUALITY_STATUSES are counted in
    total_turns but excluded from quality_turns, adoption_count, success_count,
    and quality_score.  This prevents fail-open / infrastructure errors from
    diluting the quality signal.
    """
    parsed = [_coerce(r) for r in records]
    total_turns = len(parsed)

    quality_records = [r for r in parsed if r.adoption_status not in EXCLUDED_QUALITY_STATUSES]
    quality_turns = len(quality_records)

    adoption_count = sum(1 for r in quality_records if r.adoption_status in {"adopted", "partial"})
    success_count = sum(1 for r in quality_records if r.outcome in _SUCCESS_OUTCOMES)
    quality_score = success_count / quality_turns if quality_turns > 0 else 0.0

    evidence_expansions: dict[str, list[bool]] = {}
    for r in quality_records:
        for ev_id in r.evidence_ids_expanded:
            evidence_expansions.setdefault(ev_id, []).append(r.outcome in _SUCCESS_OUTCOMES)

    evidence_feedback: dict[str, EvidenceFeedback] = {}
    for ev_id, successes in evidence_expansions.items():
        exp_count = len(successes)
        succ_count = sum(successes)
        evidence_feedback[ev_id] = EvidenceFeedback(
            evidence_id=ev_id,
            expansion_count=exp_count,
            success_count=succ_count,
            quality_score=succ_count / exp_count,
        )

    return PackFeedback(
        total_turns=total_turns,
        quality_turns=quality_turns,
        adoption_count=adoption_count,
        success_count=success_count,
        quality_score=quality_score,
        evidence_feedback=evidence_feedback,
    )


def _coerce(record: RawContextPackEvalRecord) -> ContextPackEvalRecord:
    if isinstance(record, ContextPackEvalRecord):
        return record
    return ContextPackEvalRecord.model_validate(record)


__all__ = [
    "EXCLUDED_QUALITY_STATUSES",
    "EvidenceFeedback",
    "PackFeedback",
    "aggregate_anvil_feedback",
]
