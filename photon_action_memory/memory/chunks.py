"""ActionChunker - groups StoredEvents into ActionChunk units."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionChunk,
)
from photon_action_memory.memory.store import StoredEvent

# Maps event_type to ChunkKind literal.
_EVENT_KIND_MAP: dict[str, str] = {
    "answer": "answer_prep",
    "bash": "other",
    "edit": "edit_attempt",
    "error": "failure_reproduction",
    "failure": "failure_reproduction",
    "file_create": "edit_attempt",
    "file_delete": "edit_attempt",
    "file_edit": "edit_attempt",
    "file_read": "file_inspection",
    "file_write": "edit_attempt",
    "grep": "repo_search",
    "repo_search": "repo_search",
    "search": "repo_search",
    "test_result": "test_verification",
    "test_run": "test_verification",
}

_VALID_OUTCOMES: frozenset[str] = frozenset(
    ["failed", "irrelevant", "partial", "unknown", "useful"]
)

_VALID_RISKS: frozenset[str] = frozenset(["high", "low", "medium"])

_STATUS_TO_OUTCOME: dict[str, str] = {
    "error": "failed",
    "failed": "failed",
    "failure": "failed",
    "ok": "useful",
    "passed": "useful",
    "success": "useful",
}

_MEDIUM_RISK_KINDS: frozenset[str] = frozenset(["edit_attempt", "failure_reproduction"])


def _infer_kind(events: list[StoredEvent]) -> str:
    kind_counts: dict[str, int] = {}
    for event in events:
        kind = _EVENT_KIND_MAP.get(event.event_type.lower(), "other")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
    if not kind_counts:
        return "other"
    return max(kind_counts, key=lambda k: (kind_counts[k], k))


def _infer_outcome(events: list[StoredEvent]) -> str:
    for event in reversed(events):
        payload = event.payload
        outcome = payload.get("outcome")
        if isinstance(outcome, str) and outcome in _VALID_OUTCOMES:
            return outcome
        status = payload.get("status")
        if isinstance(status, str):
            mapped = _STATUS_TO_OUTCOME.get(status.lower())
            if mapped is not None:
                return mapped
    return "unknown"


def _infer_risk(events: list[StoredEvent]) -> str | None:
    for event in events:
        risk = event.payload.get("risk")
        if isinstance(risk, str) and risk in _VALID_RISKS:
            return risk
    kinds = {_EVENT_KIND_MAP.get(e.event_type.lower(), "other") for e in events}
    if kinds & _MEDIUM_RISK_KINDS:
        return "medium"
    return None


def _build_summary(kind: str, events: list[StoredEvent]) -> str:
    n = len(events)
    event_types = sorted({e.event_type for e in events})
    type_str = ", ".join(event_types[:3])
    if len(event_types) > 3:
        type_str += f", +{len(event_types) - 3} more"
    plural = "s" if n != 1 else ""
    return f"{kind} ({n} event{plural}: {type_str})"


def _deterministic_chunk_id(event_ids: list[str]) -> str:
    """Produce a stable chunk_id from sorted event IDs via SHA-256."""
    key = "\n".join(sorted(event_ids))
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f"chunk-{digest}"


def _infer_redaction_status(events: list[StoredEvent]) -> str:
    statuses = [e.payload.get("redaction_status") for e in events]
    if "redacted" in statuses:
        return "redacted"
    if all(s == "clean" for s in statuses):
        return "clean"
    return "unknown"


class ActionChunker:
    """Groups sanitized StoredEvents into ActionChunk units.

    Default grouping: events sharing the same (session_id, turn_id) form one
    chunk. All input events must already be sanitized (guaranteed by EventStore).
    Chunk IDs are deterministic: the same set of event IDs always yields the
    same chunk_id, regardless of list order.
    """

    def chunk(self, events: Sequence[StoredEvent]) -> list[ActionChunk]:
        """Group events by (session_id, turn_id), one ActionChunk per group."""
        if not events:
            return []
        groups = self._group_by_turn(list(events))
        return [self._build_chunk(group) for group in groups]

    def chunk_one(self, events: Sequence[StoredEvent]) -> ActionChunk:
        """Collapse all given events into a single ActionChunk."""
        if not events:
            msg = "events must not be empty"
            raise ValueError(msg)
        return self._build_chunk(list(events))

    def _group_by_turn(self, events: list[StoredEvent]) -> list[list[StoredEvent]]:
        seen: dict[tuple[str, str], list[StoredEvent]] = {}
        order: list[tuple[str, str]] = []
        for event in events:
            key = (event.session_id, event.turn_id)
            if key not in seen:
                seen[key] = []
                order.append(key)
            seen[key].append(event)
        return [seen[k] for k in order]

    def _build_chunk(self, events: list[StoredEvent]) -> ActionChunk:
        event_ids = [e.event_id for e in events]
        kind = _infer_kind(events)
        outcome = _infer_outcome(events)
        risk = _infer_risk(events)
        summary = _build_summary(kind, events)
        redaction_status = _infer_redaction_status(events)

        commit: str | None = None
        for e in reversed(events):
            c = e.payload.get("commit")
            if isinstance(c, str) and c:
                commit = c
                break

        return ActionChunk(
            schema_version=DEFAULT_SCHEMA_VERSION_V2,
            chunk_id=_deterministic_chunk_id(event_ids),
            session_id=events[0].session_id,
            turn_id=events[0].turn_id,
            repo_id=events[0].repo_id,
            commit=commit,
            kind=kind,
            event_ids=event_ids,
            started_at=events[0].timestamp,
            ended_at=events[-1].timestamp,
            summary=summary,
            outcome=outcome,
            risk=risk,
            redaction_status=redaction_status,
        )


__all__ = ["ActionChunker"]
