"""Feedback-adjusted context scoring for PHOTON Context Firewall.

Provides apply_feedback_boost() and FeedbackAdjustedContextScorer, which
wraps FallbackContextScorer and applies quality signals from PackFeedback.

Hard invariants (never relaxed by positive feedback):
- stale items: admission/usefulness score capped at STALE_MAX_SCORE.
- contradicted items: admission/usefulness score capped at CONTRADICTED_MAX_SCORE.
- unsafe items: treated identically to contradicted.
- Staleness risk scores are NEVER adjusted — stale stays stale.
"""

from __future__ import annotations

from collections.abc import Sequence

from photon_action_memory.api.schema_v2 import ActionSummary, EvidenceRef
from photon_action_memory.eval.anvil_feedback import PackFeedback
from photon_action_memory.models.context_scorer import (
    AdmissionScore,
    ContextScorerHook,
    EvidenceExpansionScore,
    FallbackContextScorer,
    ScoringEvent,
    StalenessRiskScore,
    SummaryUsefulnessScore,
)

# Hard caps on scores for items that must not recover via feedback.
# These sit above the natural deterministic max for stale/contradicted items
# (stale max ≈ 0.20, contradicted max ≈ 0.10) but well below valid item scores,
# so feedback cannot cause a stale item to rank above a valid one.
STALE_MAX_SCORE: float = 0.25
CONTRADICTED_MAX_SCORE: float = 0.15

# Maximum additive boost from a quality_score of 1.0 (as a fraction of [0,1]).
# Keeps the boost bounded so structural signals dominate.
MAX_QUALITY_BOOST: float = 0.2

# Additional boost from explicit user-positive signal (Anvil PR #599
# ``user_positive`` / ``user_rule`` outcomes). Layered on top of
# MAX_QUALITY_BOOST so an explicit thumbs-up pushes a valid item higher
# than an equivalent implicit success. Combined max boost remains bounded
# (0.30) and the per-status hard caps still apply.
MAX_USER_SIGNAL_BOOST: float = 0.1

_BLOCKED_STATUSES: frozenset[str] = frozenset({"stale", "contradicted", "unsafe"})


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _score_cap(status: str) -> float:
    """Hard cap on adjusted score for unsafe validity/staleness statuses."""
    if status in {"contradicted", "unsafe"}:
        return CONTRADICTED_MAX_SCORE
    if status == "stale":
        return STALE_MAX_SCORE
    return 1.0


def apply_feedback_boost(
    base_score: float,
    status: str,
    quality_score: float,
    *,
    max_boost: float = MAX_QUALITY_BOOST,
    user_signal: float = 0.0,
    max_user_boost: float = MAX_USER_SIGNAL_BOOST,
) -> float:
    """Apply a bounded feedback quality boost to a base score.

    ``quality_score * max_boost`` plus ``user_signal * max_user_boost`` is
    added to ``base_score``, then clamped to ``[0, 1]``. The result is
    finally hard-capped by ``_score_cap(status)`` so stale, contradicted,
    or unsafe items can never recover into valid-item score ranges.

    ``user_signal`` is the explicit-user-positive ratio from
    ``PackFeedback.user_signal_score`` (Anvil PR #599). It stacks on top
    of the implicit-success boost so an explicit thumbs-up outranks an
    equivalent implicit success.
    """
    boosted = _clamp(base_score + quality_score * max_boost + user_signal * max_user_boost)
    return _clamp(min(boosted, _score_cap(status)))


class FeedbackAdjustedContextScorer:
    """FallbackContextScorer with Anvil evaluate feedback adjustment.

    Applies aggregate quality signals from PackFeedback:

    - score_admission: base score boosted by pack quality_score, hard-capped
      for stale/contradicted/unsafe summaries.
    - score_evidence_expansion: base score boosted by per-evidence
      quality_score (falls back to pack quality_score if not seen before),
      hard-capped for stale evidence.
    - score_summary_usefulness: same boost logic as admission.
    - score_staleness_risk: NEVER adjusted — stale/contradicted stay stale.

    Satisfies ContextScorerProtocol so it can be injected wherever
    FallbackContextScorer is accepted.
    """

    def __init__(
        self,
        feedback: PackFeedback,
        *,
        eval_hook: ContextScorerHook | None = None,
    ) -> None:
        self._feedback = feedback
        self._base = FallbackContextScorer()
        self._hook = eval_hook

    def score_admission(
        self,
        summaries: Sequence[ActionSummary],
        *,
        task_text: str = "",
    ) -> list[AdmissionScore]:
        base_results = self._base.score_admission(summaries, task_text=task_text)
        adjusted: list[AdmissionScore] = []
        for summary, base in zip(summaries, base_results, strict=False):
            new_score = apply_feedback_boost(
                base.score,
                summary.validity.status,
                self._feedback.quality_score,
                user_signal=self._feedback.user_signal_score,
            )
            reason = (
                f"{base.reason} feedback_boost={self._feedback.quality_score:.2f}"
                f" user_signal={self._feedback.user_signal_score:.2f}"
            )
            result = AdmissionScore(
                summary_id=summary.summary_id,
                score=new_score,
                reason=reason,
            )
            adjusted.append(result)
            if self._hook is not None:
                self._hook(ScoringEvent("admission", summary.summary_id, new_score, reason))
        return adjusted

    def score_evidence_expansion(
        self,
        evidence_refs: Sequence[EvidenceRef],
        *,
        task_text: str = "",
    ) -> list[EvidenceExpansionScore]:
        base_results = self._base.score_evidence_expansion(evidence_refs, task_text=task_text)
        adjusted: list[EvidenceExpansionScore] = []
        for ref, base in zip(evidence_refs, base_results, strict=False):
            ev_feedback = self._feedback.evidence_feedback.get(ref.evidence_id)
            quality = (
                ev_feedback.quality_score
                if ev_feedback is not None
                else self._feedback.quality_score
            )
            new_score = apply_feedback_boost(
                base.score,
                ref.staleness.status,
                quality,
                user_signal=self._feedback.user_signal_score,
            )
            reason = (
                f"{base.reason} feedback_boost={quality:.2f}"
                f" user_signal={self._feedback.user_signal_score:.2f}"
            )
            result = EvidenceExpansionScore(
                evidence_id=ref.evidence_id,
                score=new_score,
                reason=reason,
            )
            adjusted.append(result)
            if self._hook is not None:
                self._hook(ScoringEvent("evidence_expansion", ref.evidence_id, new_score, reason))
        return adjusted

    def score_summary_usefulness(
        self,
        summaries: Sequence[ActionSummary],
        *,
        task_text: str = "",
    ) -> list[SummaryUsefulnessScore]:
        base_results = self._base.score_summary_usefulness(summaries, task_text=task_text)
        adjusted: list[SummaryUsefulnessScore] = []
        for summary, base in zip(summaries, base_results, strict=False):
            new_score = apply_feedback_boost(
                base.score,
                summary.validity.status,
                self._feedback.quality_score,
                user_signal=self._feedback.user_signal_score,
            )
            reason = (
                f"{base.reason} feedback_boost={self._feedback.quality_score:.2f}"
                f" user_signal={self._feedback.user_signal_score:.2f}"
            )
            result = SummaryUsefulnessScore(
                summary_id=summary.summary_id,
                score=new_score,
                reason=reason,
            )
            adjusted.append(result)
            if self._hook is not None:
                self._hook(
                    ScoringEvent("summary_usefulness", summary.summary_id, new_score, reason)
                )
        return adjusted

    def score_staleness_risk(
        self,
        summaries: Sequence[ActionSummary],
    ) -> list[StalenessRiskScore]:
        # Staleness risk is structural; positive feedback cannot reduce it.
        return self._base.score_staleness_risk(summaries)


__all__ = [
    "CONTRADICTED_MAX_SCORE",
    "MAX_QUALITY_BOOST",
    "MAX_USER_SIGNAL_BOOST",
    "STALE_MAX_SCORE",
    "FeedbackAdjustedContextScorer",
    "apply_feedback_boost",
]
