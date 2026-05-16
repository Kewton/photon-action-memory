"""ActionMemoryPhotonScorer boundary.

Adds an opt-in scorer over summary / evidence / next_hint / failed_attempt
candidates with a deterministic fallback when MLX or the PHOTON checkpoint
is unavailable. The scorer is a pure compute boundary — no /v1 endpoint is
wired in this Issue; callers can construct the scorer via
:func:`make_action_memory_scorer` and rank candidates inline.

Both the deterministic and the MLX-backed scorer share the same DTOs and
return :class:`ActionMemoryScoreResult` so callers do not need to branch on
the implementation.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from photon_action_memory.models.checkpoint import CheckpointError
from photon_action_memory.models.photon_adapter import (
    CHECKPOINT_ENV,
    CHECKPOINT_STRICT_ENV,
    PHOTON_MODEL_VERSION,
    PhotonAdapterError,
    PhotonMLXAdapter,
)
from photon_action_memory.models.state import PhotonScoringState

_logger = logging.getLogger(__name__)

DETERMINISTIC_MODEL_VERSION = "deterministic-overlap-v1"

_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "with",
    }
)


# ---------------------------------------------------------------------------
# Candidate / score DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SummaryCandidate:
    summary_id: str
    text: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceCandidate:
    evidence_id: str
    text: str


@dataclass(frozen=True)
class NextHintCandidate:
    index: int
    kind: str
    reason: str
    target: str | None = None


@dataclass(frozen=True)
class FailedAttemptCandidate:
    index: int
    action: str
    outcome: str


@dataclass(frozen=True)
class ScoredSummary:
    summary_id: str
    score: float
    reason: str


@dataclass(frozen=True)
class ScoredEvidence:
    evidence_id: str
    score: float
    reason: str


@dataclass(frozen=True)
class ScoredNextHint:
    index: int
    score: float
    reason: str


@dataclass(frozen=True)
class ScoredFailedAttempt:
    index: int
    score: float
    reason: str


@dataclass(frozen=True)
class ActionMemoryScoreResult:
    summary_scores: tuple[ScoredSummary, ...] = ()
    evidence_scores: tuple[ScoredEvidence, ...] = ()
    next_hint_scores: tuple[ScoredNextHint, ...] = ()
    failure_similarity: tuple[ScoredFailedAttempt, ...] = ()
    drift_score: float | None = None
    model_version: str = DETERMINISTIC_MODEL_VERSION
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class ActionMemoryPhotonScorer(Protocol):
    """Scorer boundary over ranked Action Memory candidates."""

    def score(
        self,
        *,
        request_id: str,
        repo_id: str | None,
        task_text: str,
        session_id: str | None = None,
        session_state_ref: None = None,
        candidate_summaries: Sequence[SummaryCandidate] = (),
        candidate_evidence: Sequence[EvidenceCandidate] = (),
        candidate_next_hints: Sequence[NextHintCandidate] = (),
        candidate_failed_attempts: Sequence[FailedAttemptCandidate] = (),
    ) -> ActionMemoryScoreResult: ...


# ---------------------------------------------------------------------------
# Deterministic fallback
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeterministicActionMemoryScorer:
    """Pure lexical-overlap scorer used when PHOTON/MLX is unavailable.

    Scores are bounded in ``[0, 1]`` and stable across runs so downstream
    ranking remains deterministic. ``warnings`` propagates the reason the
    deterministic path was chosen (e.g. ``"photon_unavailable"``) when the
    scorer was selected by the factory after a PHOTON construction failure.
    """

    warnings: tuple[str, ...] = ()

    def score(
        self,
        *,
        request_id: str,  # noqa: ARG002 — present for protocol parity
        repo_id: str | None,  # noqa: ARG002
        task_text: str,
        session_id: str | None = None,  # noqa: ARG002
        session_state_ref: None = None,  # noqa: ARG002
        candidate_summaries: Sequence[SummaryCandidate] = (),
        candidate_evidence: Sequence[EvidenceCandidate] = (),
        candidate_next_hints: Sequence[NextHintCandidate] = (),
        candidate_failed_attempts: Sequence[FailedAttemptCandidate] = (),
    ) -> ActionMemoryScoreResult:
        task_tokens = _tokens(task_text)

        summary_scores = tuple(
            ScoredSummary(
                summary_id=cand.summary_id,
                score=_overlap_with_boost(task_tokens, cand.text, bool(cand.evidence_ids)),
                reason=(
                    "lexical overlap; +0.05 evidence boost"
                    if cand.evidence_ids
                    else "lexical overlap"
                ),
            )
            for cand in candidate_summaries
        )
        evidence_scores = tuple(
            ScoredEvidence(
                evidence_id=cand.evidence_id,
                score=_overlap(task_tokens, cand.text),
                reason="lexical overlap on evidence text",
            )
            for cand in candidate_evidence
        )
        next_hint_scores = tuple(
            ScoredNextHint(
                index=cand.index,
                score=_overlap(task_tokens, _join(cand.reason, cand.target)),
                reason="lexical overlap on next-hint text",
            )
            for cand in candidate_next_hints
        )
        failure_scores = tuple(
            ScoredFailedAttempt(
                index=cand.index,
                score=_overlap(task_tokens, _join(cand.outcome, cand.action)),
                reason="lexical overlap on failed-attempt text",
            )
            for cand in candidate_failed_attempts
        )
        return ActionMemoryScoreResult(
            summary_scores=summary_scores,
            evidence_scores=evidence_scores,
            next_hint_scores=next_hint_scores,
            failure_similarity=failure_scores,
            drift_score=None,
            model_version=DETERMINISTIC_MODEL_VERSION,
            warnings=self.warnings,
        )


def _tokens(text: str) -> set[str]:
    return {
        word
        for word in _TOKEN_RE.findall(text.lower())
        if len(word) > 2 and word not in _STOP_WORDS
    }


def _overlap(task_tokens: set[str], text: str) -> float:
    if not task_tokens:
        return 0.0
    cand_tokens = _tokens(text)
    if not cand_tokens:
        return 0.0
    inter = task_tokens & cand_tokens
    union = task_tokens | cand_tokens
    if not union:
        return 0.0
    return round(len(inter) / len(union), 4)


def _overlap_with_boost(task_tokens: set[str], text: str, has_evidence: bool) -> float:
    base = _overlap(task_tokens, text)
    if has_evidence:
        base = min(1.0, base + 0.05)
    return round(base, 4)


def _join(*parts: str | None) -> str:
    return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# PHOTON/MLX scorer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhotonMLXActionMemoryScorer:
    """Thin adapter around :class:`PhotonMLXAdapter` for Action Memory ranking."""

    adapter: PhotonMLXAdapter
    fallback: DeterministicActionMemoryScorer = field(
        default_factory=DeterministicActionMemoryScorer,
    )

    def score(
        self,
        *,
        request_id: str,
        repo_id: str | None,
        task_text: str,
        session_id: str | None = None,
        session_state_ref: None = None,
        candidate_summaries: Sequence[SummaryCandidate] = (),
        candidate_evidence: Sequence[EvidenceCandidate] = (),
        candidate_next_hints: Sequence[NextHintCandidate] = (),
        candidate_failed_attempts: Sequence[FailedAttemptCandidate] = (),
    ) -> ActionMemoryScoreResult:
        state = PhotonScoringState(
            request_id=request_id,
            task_text=task_text,
            touched_files=(),
            recent_event_summaries=(),
            evidence_summaries=tuple(cand.text for cand in candidate_evidence),
        )
        model_version = self.adapter.checkpoint.model_version or PHOTON_MODEL_VERSION
        try:
            summary_scores = tuple(
                ScoredSummary(
                    summary_id=cand.summary_id,
                    score=self.adapter._score("summary", cand.text, state),
                    reason=f"PHOTON MLX scored summary {cand.summary_id!r}",
                )
                for cand in candidate_summaries
            )
            evidence_scores = tuple(
                ScoredEvidence(
                    evidence_id=cand.evidence_id,
                    score=self.adapter._score("evidence", cand.text, state),
                    reason="PHOTON MLX scored evidence",
                )
                for cand in candidate_evidence
            )
            next_hint_scores = tuple(
                ScoredNextHint(
                    index=cand.index,
                    score=self.adapter._score("next_hint", _join(cand.reason, cand.target), state),
                    reason="PHOTON MLX scored next-hint",
                )
                for cand in candidate_next_hints
            )
            failure_scores = tuple(
                ScoredFailedAttempt(
                    index=cand.index,
                    score=self.adapter._score(
                        "failed_attempt",
                        _join(cand.outcome, cand.action),
                        state,
                    ),
                    reason="PHOTON MLX scored failed-attempt",
                )
                for cand in candidate_failed_attempts
            )
        except PhotonAdapterError as exc:
            _logger.warning("PHOTON scoring failed (%s); using deterministic fallback", exc)
            result = self.fallback.score(
                request_id=request_id,
                repo_id=repo_id,
                task_text=task_text,
                session_id=session_id,
                session_state_ref=session_state_ref,
                candidate_summaries=candidate_summaries,
                candidate_evidence=candidate_evidence,
                candidate_next_hints=candidate_next_hints,
                candidate_failed_attempts=candidate_failed_attempts,
            )
            return ActionMemoryScoreResult(
                summary_scores=result.summary_scores,
                evidence_scores=result.evidence_scores,
                next_hint_scores=result.next_hint_scores,
                failure_similarity=result.failure_similarity,
                drift_score=None,
                model_version=DETERMINISTIC_MODEL_VERSION,
                warnings=("photon_unavailable",),
            )

        return ActionMemoryScoreResult(
            summary_scores=summary_scores,
            evidence_scores=evidence_scores,
            next_hint_scores=next_hint_scores,
            failure_similarity=failure_scores,
            drift_score=None,
            model_version=model_version,
            warnings=(),
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_action_memory_scorer(
    env: Mapping[str, str] | None = None,
) -> ActionMemoryPhotonScorer:
    """Construct the configured scorer, falling back to deterministic on failure.

    The factory never raises: a missing checkpoint, missing MLX, or checkpoint
    error simply yields :class:`DeterministicActionMemoryScorer` with the
    ``"photon_unavailable"`` warning so downstream telemetry can record the
    reason without breaking the request.
    """
    environment = env if env is not None else os.environ
    raw = (environment.get(CHECKPOINT_ENV) or "").strip()
    if not raw:
        return DeterministicActionMemoryScorer()
    try:
        adapter = PhotonMLXAdapter.from_checkpoint(
            Path(raw),
            strict=_strict_checkpoint_mode(environment),
        )
    except (OSError, ValueError, CheckpointError, PhotonAdapterError):
        return DeterministicActionMemoryScorer(warnings=("photon_unavailable",))
    return PhotonMLXActionMemoryScorer(adapter=adapter)


def _strict_checkpoint_mode(environment: Mapping[str, str]) -> bool:
    raw_value = environment.get(CHECKPOINT_STRICT_ENV, "").strip().lower()
    return raw_value in {"1", "true", "yes", "on", "strict"}


__all__ = [
    "ActionMemoryPhotonScorer",
    "ActionMemoryScoreResult",
    "DETERMINISTIC_MODEL_VERSION",
    "DeterministicActionMemoryScorer",
    "EvidenceCandidate",
    "FailedAttemptCandidate",
    "NextHintCandidate",
    "PhotonMLXActionMemoryScorer",
    "ScoredEvidence",
    "ScoredFailedAttempt",
    "ScoredNextHint",
    "ScoredSummary",
    "SummaryCandidate",
    "make_action_memory_scorer",
]
