"""Per-summary feedback aggregation derived from /v1/evaluate outcomes.

Builds on the same fail-open exclusion rules as `anvil_feedback`: error /
not_available / shadow_not_injected turns do not contribute to per-summary
confidence. The aggregate is counter-only — no raw prompts, tool output, or
user text is stored, so the table is safe for future feature extraction.
"""

from __future__ import annotations

from dataclasses import dataclass

from photon_action_memory.eval.anvil_feedback import EXCLUDED_QUALITY_STATUSES

_SUCCESS_OUTCOMES: frozenset[str] = frozenset({"success", "accepted", "completed"})
_SAFETY_OUTCOMES: frozenset[str] = frozenset({"safety_violation", "unsafe", "harmful"})
_ADOPTED_STATUSES: frozenset[str] = frozenset({"adopted", "partial"})

# Demote / disable thresholds — S2-03 regression pattern: after enough adoptions
# with predominantly non-success outcomes, the summary is considered unhelpful.
MIN_ADOPTIONS_FOR_DISABLE: int = 3
DISABLE_CONFIDENCE_THRESHOLD: float = 0.34


@dataclass(frozen=True)
class SummaryFeedbackRecord:
    """Per-summary aggregate feedback derived from /v1/evaluate logs.

    All fields are counters or rates. Never carries raw prompt or tool output.
    """

    summary_id: str
    adoption_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    safety_violation_count: int = 0
    expand_request_count: int = 0
    quality_turns: int = 0


def confidence(record: SummaryFeedbackRecord) -> float:
    """Laplace-smoothed confidence that adopting *summary* leads to success.

    Returns 0.5 when no adoption has been observed (neutral prior), so unseen
    summaries are not penalised. Smoothing keeps a single failure from pinning
    confidence to 0.
    """
    successes = record.success_count
    failures = record.failure_count
    return (successes + 1) / (successes + failures + 2)


def is_disabled(record: SummaryFeedbackRecord) -> bool:
    """Return True if the summary should be excluded from new ContextPacks.

    Disable conditions (in priority order):
    1. Any safety violation — zero tolerance.
    2. Repeated adoptions with low confidence (S2-03 regression).
    """
    if record.safety_violation_count >= 1:
        return True
    if (
        record.adoption_count >= MIN_ADOPTIONS_FOR_DISABLE
        and confidence(record) < DISABLE_CONFIDENCE_THRESHOLD
    ):
        return True
    return False


def classify_outcome(
    adoption_status: str,
    outcome: str | None,
) -> tuple[bool, str]:
    """Classify a single evaluate record's contribution.

    Returns a (is_quality_turn, classification) tuple where classification is
    one of ``"success"``, ``"failure"``, ``"safety"``, or ``"none"``.
    Non-quality turns (excluded statuses) yield ``(False, "none")``.
    """
    if adoption_status in EXCLUDED_QUALITY_STATUSES:
        return False, "none"
    if outcome in _SAFETY_OUTCOMES:
        return True, "safety"
    if outcome in _SUCCESS_OUTCOMES:
        return True, "success"
    return True, "failure"


def is_adopted(adoption_status: str) -> bool:
    """Return True if the record's status counts as adoption."""
    return adoption_status in _ADOPTED_STATUSES


__all__ = [
    "DISABLE_CONFIDENCE_THRESHOLD",
    "MIN_ADOPTIONS_FOR_DISABLE",
    "SummaryFeedbackRecord",
    "classify_outcome",
    "confidence",
    "is_adopted",
    "is_disabled",
]
