"""Context Firewall scoring interfaces for PHOTON.

Provides score result types, a runtime-checkable Protocol, and a deterministic
FallbackContextScorer that requires no trained model.

This module is MLX-free at import time; normal imports never touch mlx.core.
An optional eval_hook callable receives a ScoringEvent after each scored item,
enabling integration with the eval comparison framework (eval/comparison.py).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from photon_action_memory.api.schema_v2 import ActionSummary, EvidenceRef

# ---------------------------------------------------------------------------
# Score result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdmissionScore:
    """Admission priority score for an ActionSummary."""

    summary_id: str
    score: float  # 0.0 = low priority, 1.0 = high priority
    reason: str


@dataclass(frozen=True)
class EvidenceExpansionScore:
    """Expansion priority score for an EvidenceRef."""

    evidence_id: str
    score: float  # 0.0 = skip, 1.0 = expand first
    reason: str


@dataclass(frozen=True)
class SummaryUsefulnessScore:
    """Usefulness score for an ActionSummary relative to the current task."""

    summary_id: str
    score: float  # 0.0 = not useful, 1.0 = highly useful
    reason: str


@dataclass(frozen=True)
class StalenessRiskScore:
    """Staleness risk score for an ActionSummary."""

    summary_id: str
    risk: float  # 0.0 = fresh, 1.0 = highly stale
    reason: str


# ---------------------------------------------------------------------------
# Eval hook support
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoringEvent:
    """Emitted to the optional eval_hook after each scored item.

    scorer_kind is one of: "admission", "evidence_expansion",
    "summary_usefulness", "staleness_risk".  Callers may aggregate these
    events into ComparisonRecord fields for the eval/comparison framework.
    """

    scorer_kind: str
    item_id: str
    score: float
    reason: str


ContextScorerHook = Callable[[ScoringEvent], None]


# ---------------------------------------------------------------------------
# ContextScorerProtocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ContextScorerProtocol(Protocol):
    """Runtime-checkable Protocol for PHOTON Context Firewall scorers.

    Implementations must remain importable without MLX. Use
    FallbackContextScorer when no model is configured.
    """

    def score_admission(
        self,
        summaries: Sequence[ActionSummary],
        *,
        task_text: str = "",
    ) -> list[AdmissionScore]: ...

    def score_evidence_expansion(
        self,
        evidence_refs: Sequence[EvidenceRef],
        *,
        task_text: str = "",
    ) -> list[EvidenceExpansionScore]: ...

    def score_summary_usefulness(
        self,
        summaries: Sequence[ActionSummary],
        *,
        task_text: str = "",
    ) -> list[SummaryUsefulnessScore]: ...

    def score_staleness_risk(
        self,
        summaries: Sequence[ActionSummary],
    ) -> list[StalenessRiskScore]: ...


# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------

# Staleness risk mapped from validity.status
_STALENESS_RISK: dict[str, float] = {
    "valid": 0.0,
    "partial": 0.3,
    "unknown": 0.5,
    "stale": 0.8,
    "contradicted": 1.0,
}

# Admission multiplier per validity status
_VALIDITY_ADMISSION_FACTOR: dict[str, float] = {
    "valid": 1.0,
    "partial": 0.7,
    "unknown": 0.5,
    "stale": 0.2,
    "contradicted": 0.1,
}

# Base expansion score per expand_policy
_EXPAND_POLICY_BASE: dict[str, float] = {
    "always": 0.9,
    "on_demand_only": 0.5,
    "deny": 0.0,
}

# Weighted content count that maps to a raw admission score of 1.0
_RICHNESS_CEILING = 12


# ---------------------------------------------------------------------------
# FallbackContextScorer
# ---------------------------------------------------------------------------


class FallbackContextScorer:
    """Deterministic context scorer that requires no trained model.

    Scores derive entirely from structural properties of the summaries:

    - Admission: weighted content count × validity factor.
    - Evidence expansion: expand_policy base × staleness adjustment.
    - Summary usefulness: task-text word overlap + content richness.
    - Staleness risk: direct mapping from validity.status.

    All scores are clamped to [0.0, 1.0].  Calling the same scorer with the
    same inputs always returns the same result (no randomness).
    """

    def __init__(self, *, eval_hook: ContextScorerHook | None = None) -> None:
        self._hook = eval_hook

    def score_admission(
        self,
        summaries: Sequence[ActionSummary],
        *,
        task_text: str = "",
    ) -> list[AdmissionScore]:
        """Score summaries for context admission priority."""
        results: list[AdmissionScore] = []
        for summary in summaries:
            score, reason = _admission_score(summary)
            result = AdmissionScore(summary_id=summary.summary_id, score=score, reason=reason)
            results.append(result)
            if self._hook is not None:
                self._hook(ScoringEvent("admission", summary.summary_id, score, reason))
        return results

    def score_evidence_expansion(
        self,
        evidence_refs: Sequence[EvidenceRef],
        *,
        task_text: str = "",
    ) -> list[EvidenceExpansionScore]:
        """Score evidence refs for expansion priority."""
        results: list[EvidenceExpansionScore] = []
        for ref in evidence_refs:
            score, reason = _expansion_score(ref)
            result = EvidenceExpansionScore(evidence_id=ref.evidence_id, score=score, reason=reason)
            results.append(result)
            if self._hook is not None:
                self._hook(ScoringEvent("evidence_expansion", ref.evidence_id, score, reason))
        return results

    def score_summary_usefulness(
        self,
        summaries: Sequence[ActionSummary],
        *,
        task_text: str = "",
    ) -> list[SummaryUsefulnessScore]:
        """Score summaries by usefulness for the current task."""
        results: list[SummaryUsefulnessScore] = []
        for summary in summaries:
            score, reason = _usefulness_score(summary, task_text)
            result = SummaryUsefulnessScore(
                summary_id=summary.summary_id, score=score, reason=reason
            )
            results.append(result)
            if self._hook is not None:
                self._hook(ScoringEvent("summary_usefulness", summary.summary_id, score, reason))
        return results

    def score_staleness_risk(
        self,
        summaries: Sequence[ActionSummary],
    ) -> list[StalenessRiskScore]:
        """Score summaries for staleness risk."""
        results: list[StalenessRiskScore] = []
        for summary in summaries:
            risk, reason = _staleness_risk(summary)
            result = StalenessRiskScore(summary_id=summary.summary_id, risk=risk, reason=reason)
            results.append(result)
            if self._hook is not None:
                self._hook(ScoringEvent("staleness_risk", summary.summary_id, risk, reason))
        return results


# ---------------------------------------------------------------------------
# Internal scoring helpers
# ---------------------------------------------------------------------------


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _content_richness(summary: ActionSummary) -> int:
    """Weighted count of content items; higher = richer summary."""
    return (
        len(summary.facts) * 3
        + len(summary.hypotheses) * 2
        + len(summary.failed_attempts)
        + len(summary.avoid)
    )


def _task_overlap(summary: ActionSummary, task_text: str) -> float:
    """Word-level overlap between task_text and summary fact/hypothesis texts."""
    if not task_text:
        return 0.0
    task_words = set(task_text.lower().split())
    if not task_words:
        return 0.0
    content_parts: list[str] = [f.text for f in summary.facts]
    content_parts.extend(h.text for h in summary.hypotheses)
    content_text = " ".join(content_parts)
    content_words = set(content_text.lower().split())
    if not content_words:
        return 0.0
    return _clamp(len(task_words & content_words) / len(task_words))


def _admission_score(summary: ActionSummary) -> tuple[float, str]:
    richness = _content_richness(summary)
    if richness == 0:
        return 0.0, "fallback: no admissible content"
    validity_factor = _VALIDITY_ADMISSION_FACTOR.get(summary.validity.status, 0.5)
    raw = _clamp(richness / _RICHNESS_CEILING)
    score = _clamp(raw * validity_factor)
    return score, f"fallback: richness={richness} validity={summary.validity.status}"


def _expansion_score(ref: EvidenceRef) -> tuple[float, str]:
    base = _EXPAND_POLICY_BASE.get(ref.expand_policy, 0.5)
    if base == 0.0:
        return 0.0, "fallback: expand_policy=deny"
    staleness_penalty = _STALENESS_RISK.get(ref.staleness.status, 0.5)
    score = _clamp(base * (1.0 - staleness_penalty * 0.5))
    return score, f"fallback: policy={ref.expand_policy} staleness={ref.staleness.status}"


def _usefulness_score(summary: ActionSummary, task_text: str) -> tuple[float, str]:
    richness = _content_richness(summary)
    richness_score = _clamp(richness / _RICHNESS_CEILING)
    if not task_text:
        score = _clamp(richness_score * 0.5)
        return score, "fallback: no task context"
    overlap = _task_overlap(summary, task_text)
    score = _clamp(overlap * 0.7 + richness_score * 0.3)
    return score, f"fallback: overlap={overlap:.2f} richness={richness}"


def _staleness_risk(summary: ActionSummary) -> tuple[float, str]:
    status = summary.validity.status
    risk = _STALENESS_RISK.get(status, 0.5)
    return risk, f"fallback: validity.status={status}"


__all__ = [
    "AdmissionScore",
    "ContextScorerHook",
    "ContextScorerProtocol",
    "EvidenceExpansionScore",
    "FallbackContextScorer",
    "ScoringEvent",
    "StalenessRiskScore",
    "SummaryUsefulnessScore",
]
