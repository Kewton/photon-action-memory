"""Model-independent DTOs for optional PHOTON scoring."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PhotonScoringState:
    """Compact request state passed into optional model scorers."""

    request_id: str
    task_text: str
    touched_files: tuple[str, ...] = ()
    recent_event_summaries: tuple[str, ...] = ()
    evidence_summaries: tuple[str, ...] = ()

    @classmethod
    def from_sidecar_request(
        cls,
        request: object,
        *,
        evidence: Sequence[object] = (),
    ) -> PhotonScoringState:
        """Build scoring state from a sidecar request without importing API DTOs."""
        task = getattr(request, "task", None)
        working_memory = getattr(request, "working_memory", None)
        recent_events = getattr(request, "recent_events", ())
        task_parts = (
            str(getattr(task, "user_request", "") or ""),
            str(getattr(task, "summary", "") or ""),
        )
        return cls(
            request_id=str(getattr(request, "request_id", "") or ""),
            task_text=" ".join(part for part in task_parts if part),
            touched_files=tuple(
                str(item) for item in getattr(working_memory, "touched_files", ()) if item
            ),
            recent_event_summaries=tuple(
                str(getattr(event, "summary", "") or "") for event in recent_events
            ),
            evidence_summaries=tuple(
                str(getattr(item, "summary", "") or "") for item in evidence
            ),
        )


@dataclass(frozen=True)
class ActionCandidate:
    """Action candidate that can be scored by PHOTON without API coupling."""

    kind: str
    target: str | None = None
    command: str | None = None
    query: str | None = None
    evidence_ids: tuple[str, ...] = ()

    @property
    def subject(self) -> str:
        """Return the most specific stable key for checkpoint scoring weights."""
        return self.target or self.command or self.query or self.kind


@dataclass(frozen=True)
class ScoredCandidate:
    """Model score for an action candidate."""

    candidate: ActionCandidate
    score: float
    reason: str


@dataclass(frozen=True)
class ScoredFile:
    """Model score for a file path."""

    path: str
    score: float
    reason: str


@dataclass(frozen=True)
class ScoredEvidence:
    """Model score for an evidence item."""

    evidence_id: str
    score: float
    reason: str
