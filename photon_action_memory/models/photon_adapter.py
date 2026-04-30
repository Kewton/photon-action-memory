"""Optional PHOTON/MLX scoring adapter.

This module must remain importable without MLX installed. MLX is imported only
when a checkpoint is configured and the optional adapter is constructed.
"""

from __future__ import annotations

import importlib
import math
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

from photon_action_memory.api.schema import EvidenceItem, Suggestion, SuggestRequest
from photon_action_memory.models.checkpoint import (
    CheckpointError,
    PhotonCheckpoint,
    load_checkpoint_manifest,
)
from photon_action_memory.models.state import (
    ActionCandidate,
    PhotonScoringState,
    ScoredCandidate,
    ScoredEvidence,
    ScoredFile,
)

CHECKPOINT_ENV = "PHOTON_ACTION_MEMORY_CHECKPOINT"
PHOTON_MODEL_VERSION = "photon-action-memory-v0.1.0-mlx"


class PhotonAdapterError(RuntimeError):
    """Base class for optional PHOTON adapter failures."""


class MlxUnavailable(PhotonAdapterError):
    """Raised when the optional MLX dependency is not installed."""


class PhotonScoringUnavailable(PhotonAdapterError):
    """Raised when model scoring cannot safely continue."""


class PhotonMLXAdapter:
    """Tiny optional MLX-backed scorer used to validate the runtime boundary."""

    def __init__(self, checkpoint: PhotonCheckpoint, mlx_core: ModuleType | Any) -> None:
        self.checkpoint = checkpoint
        self._mx = mlx_core

    @classmethod
    def from_checkpoint(
        cls,
        path: str | Path,
        *,
        strict: bool = False,
        import_module: Callable[[str], ModuleType | Any] | None = None,
    ) -> PhotonMLXAdapter:
        """Build an adapter after validating checkpoint and importing MLX lazily."""
        checkpoint = load_checkpoint_manifest(path, strict=strict)
        return cls(checkpoint=checkpoint, mlx_core=_import_mlx_core(import_module))

    def score_actions(
        self,
        state: PhotonScoringState,
        candidates: Sequence[ActionCandidate],
    ) -> list[ScoredCandidate]:
        """Score action candidates in input order."""
        return [
            ScoredCandidate(
                candidate=candidate,
                score=self._score(candidate.kind, candidate.subject, state),
                reason=f"PHOTON MLX adapter scored {candidate.kind!r}.",
            )
            for candidate in candidates
        ]

    def score_files(self, state: PhotonScoringState, files: Sequence[str]) -> list[ScoredFile]:
        """Score file candidates for the later MLX smoke workflow."""
        return [
            ScoredFile(
                path=path,
                score=self._score("file", path, state),
                reason="PHOTON MLX adapter scored a file candidate.",
            )
            for path in files
        ]

    def score_evidence(
        self,
        state: PhotonScoringState,
        evidence: Sequence[EvidenceItem],
    ) -> list[ScoredEvidence]:
        """Score evidence candidates for the later MLX smoke workflow."""
        return [
            ScoredEvidence(
                evidence_id=item.id,
                score=self._score("evidence", item.id, state),
                reason="PHOTON MLX adapter scored an evidence item.",
            )
            for item in evidence
        ]

    def _score(self, kind: str, subject: str, state: PhotonScoringState) -> float:
        base = _state_float(self.checkpoint.state.get("bias"), default=0.5)
        score = base
        score += _weight_for(self.checkpoint.state.get("action_weights"), kind)
        score += _weight_for(self.checkpoint.state.get("file_weights"), subject)
        score += _weight_for(self.checkpoint.state.get("evidence_weights"), subject)
        if subject and subject in state.task_text:
            score += 0.05

        try:
            value = self._mx.array([_clamp(score)], dtype=getattr(self._mx, "float32", None))
        except Exception as exc:
            raise PhotonScoringUnavailable("MLX scoring failed") from exc
        return _array_scalar(value)


def configured_checkpoint_path(environ: os._Environ[str] | None = None) -> Path | None:
    """Return the configured adapter checkpoint path, if any."""
    raw = (environ or os.environ).get(CHECKPOINT_ENV, "").strip()
    if not raw:
        return None
    return Path(raw)


def is_model_available(
    checkpoint_path: str | Path | None = None,
    *,
    import_module: Callable[[str], ModuleType | Any] | None = None,
) -> bool:
    """Return true only when the optional MLX adapter can be constructed."""
    path = Path(checkpoint_path) if checkpoint_path is not None else configured_checkpoint_path()
    if path is None:
        return False
    try:
        PhotonMLXAdapter.from_checkpoint(path, import_module=import_module)
    except (CheckpointError, PhotonAdapterError):
        return False
    return True


def score_suggestions_with_optional_adapter(
    request: SuggestRequest,
    *,
    evidence: Sequence[EvidenceItem],
    suggestions: Sequence[Suggestion],
) -> tuple[list[Suggestion], str] | None:
    """Score fallback-generated suggestions with the optional adapter when configured."""
    checkpoint_path = configured_checkpoint_path()
    if checkpoint_path is None or not suggestions:
        return None

    try:
        adapter = PhotonMLXAdapter.from_checkpoint(checkpoint_path)
        state = PhotonScoringState.from_sidecar_request(request, evidence=evidence)
        action_candidates = [_candidate_from_suggestion(suggestion) for suggestion in suggestions]
        scored = adapter.score_actions(state, action_candidates)
    except (CheckpointError, PhotonAdapterError):
        return None

    score_by_index = {index: item.score for index, item in enumerate(scored)}
    ordered = sorted(
        enumerate(suggestions),
        key=lambda item: (-score_by_index[item[0]], item[0]),
    )
    return (
        [
            suggestion.model_copy(
                update={
                    "confidence": max(suggestion.confidence, score_by_index[index]),
                    "reason": f"{suggestion.reason} PHOTON MLX score: {score_by_index[index]:.3f}.",
                }
            )
            for index, suggestion in ordered
        ],
        adapter.checkpoint.model_version or PHOTON_MODEL_VERSION,
    )


def _import_mlx_core(
    import_module: Callable[[str], ModuleType | Any] | None = None,
) -> ModuleType | Any:
    importer = import_module or importlib.import_module
    try:
        return importer("mlx.core")
    except ModuleNotFoundError as exc:
        if exc.name in {"mlx", "mlx.core"}:
            raise MlxUnavailable("optional dependency 'mlx' is not installed") from exc
        raise


def _candidate_from_suggestion(suggestion: Suggestion) -> ActionCandidate:
    return ActionCandidate(
        kind=suggestion.kind,
        target=suggestion.target,
        command=suggestion.command,
        query=suggestion.query,
        evidence_ids=tuple(suggestion.evidence_ids),
    )


def _weight_for(raw_weights: object, key: str) -> float:
    if not isinstance(raw_weights, dict):
        return 0.0
    return _state_float(raw_weights.get(key), default=0.0)


def _state_float(value: object, *, default: float) -> float:
    if isinstance(value, int | float):
        as_float = float(value)
        if math.isfinite(as_float):
            return as_float
    return default


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _array_scalar(value: object) -> float:
    if hasattr(value, "item"):
        raw_item = value.item()
        if isinstance(raw_item, int | float | str):
            return _clamp(float(raw_item))
    if not isinstance(value, str) and isinstance(value, Sequence) and value:
        first = value[0]
        if isinstance(first, int | float | str):
            return _clamp(float(first))
    if isinstance(value, int | float | str):
        return _clamp(float(value))
    raise PhotonScoringUnavailable("MLX scoring did not return a scalar value")
