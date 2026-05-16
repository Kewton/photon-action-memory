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

# Implicit success outcomes (action completed without explicit user signal).
# Extended with the explicit-feedback values introduced by Anvil PR #599
# (Issue #592): ``user_positive`` (thumbs-up) and ``user_rule`` (user lifted
# the suggestion into a stored rule). Both indicate that the user accepted
# the action, so they count toward ``success_count`` and ``quality_score``.
_SUCCESS_OUTCOMES: frozenset[str] = frozenset(
    {"success", "accepted", "completed", "user_positive", "user_rule"}
)

# Subset of _SUCCESS_OUTCOMES sourced from explicit user feedback. Tracked
# separately so the firewall can weight an explicit thumbs-up more heavily
# than an implicit success when adjusting context scores.
_USER_POSITIVE_OUTCOMES: frozenset[str] = frozenset({"user_positive", "user_rule"})

# Explicit-user-correction outcome (Anvil PR #599). A correction means the
# user kept engaging with the suggestion but had to fix it, so the turn is
# a quality turn but not a success. Tracked in ``correction_count`` and
# excluded from ``success_count`` / ``quality_score``.
_CORRECTION_OUTCOMES: frozenset[str] = frozenset({"user_correction"})


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
    - correction_count: quality turns where the user explicitly corrected
      the action (Anvil PR #599 ``user_correction``). Reported but not
      treated as success.
    - user_positive_count, user_signal_score: subset of successes that came
      from explicit user feedback (``user_positive`` / ``user_rule``). The
      firewall can weight this signal more heavily than implicit success.
    - evidence_feedback: per-evidence expansion × outcome correlation.

    fail-open/error/not_available/shadow_not_injected records are counted in
    total_turns but excluded from quality_turns and quality_score.
    """

    total_turns: int
    quality_turns: int
    adoption_count: int
    success_count: int
    correction_count: int
    user_positive_count: int
    quality_score: float
    user_signal_score: float
    evidence_feedback: dict[str, EvidenceFeedback]


def aggregate_anvil_feedback(
    records: Sequence[RawContextPackEvalRecord],
) -> PackFeedback:
    """Build aggregate feedback from a sequence of Anvil evaluate log records.

    Records with adoption_status in EXCLUDED_QUALITY_STATUSES are counted in
    total_turns but excluded from quality_turns, adoption_count, success_count,
    and quality_score.  This prevents fail-open / infrastructure errors from
    diluting the quality signal.

    Outcome semantics (Anvil PR #599 added the ``user_*`` family):

    - ``success`` / ``accepted`` / ``completed`` — implicit success; counts
      toward ``success_count`` and ``quality_score``.
    - ``user_positive`` / ``user_rule`` — explicit user approval; counts
      toward ``success_count`` *and* ``user_positive_count`` (the latter
      drives the user-vs-implicit signal weighting downstream).
    - ``user_correction`` — user corrected the action; counts toward
      ``correction_count`` only. The turn is a quality turn but neither a
      success nor a failure-only signal — the engagement is real but the
      original action was wrong.
    - Any other non-null outcome (including ``user_negative`` and
      ``failure``) is treated as a non-success quality turn.
    """
    parsed = [_coerce(r) for r in records]
    total_turns = len(parsed)

    quality_records = [r for r in parsed if r.adoption_status not in EXCLUDED_QUALITY_STATUSES]
    quality_turns = len(quality_records)

    adoption_count = sum(1 for r in quality_records if r.adoption_status in {"adopted", "partial"})
    success_count = sum(1 for r in quality_records if r.outcome in _SUCCESS_OUTCOMES)
    correction_count = sum(1 for r in quality_records if r.outcome in _CORRECTION_OUTCOMES)
    user_positive_count = sum(1 for r in quality_records if r.outcome in _USER_POSITIVE_OUTCOMES)
    quality_score = success_count / quality_turns if quality_turns > 0 else 0.0
    user_signal_score = user_positive_count / quality_turns if quality_turns > 0 else 0.0

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
        correction_count=correction_count,
        user_positive_count=user_positive_count,
        quality_score=quality_score,
        user_signal_score=user_signal_score,
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
