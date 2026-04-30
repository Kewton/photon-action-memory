"""FastAPI sidecar entrypoint."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from photon_action_memory import SCHEMA_VERSION, __version__
from photon_action_memory.api.schema import (
    FALLBACK_MODEL_VERSION,
    EventRequest,
    EventResponse,
    EvidenceItem,
    HealthResponse,
    Suggestion,
    SuggestRequest,
    SuggestResponse,
    WarningMessage,
)
from photon_action_memory.memory.store import SQLiteEventStore
from photon_action_memory.models.photon_adapter import is_model_available
from photon_action_memory.ranking.candidates import extract_candidates


def health_payload() -> dict[str, str]:
    """Return a minimal health payload for direct client smoke checks."""
    return {"status": "ok", "schema_version": SCHEMA_VERSION}


def default_store_path() -> Path:
    configured = os.environ.get("PHOTON_ACTION_MEMORY_DB")
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "photon-action-memory" / "events.sqlite"


def create_app(store: SQLiteEventStore | None = None) -> FastAPI:
    event_store = store or SQLiteEventStore(default_store_path())
    app = FastAPI(title="PHOTON Action Memory", version=__version__)
    app.state.event_store = event_store

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(**health_payload())

    @app.post("/v1/events", response_model=EventResponse)
    def append_event(event: EventRequest) -> EventResponse:
        stored = event_store.append(event.model_dump(mode="json"))
        return EventResponse(status="stored", event_id=stored.event_id, stored=True)

    @app.post("/v1/suggest", response_model=SuggestResponse)
    def suggest(request: SuggestRequest) -> SuggestResponse:
        return build_fallback_suggestions(request)

    @app.post("/v1/summarize")
    def summarize_stub() -> None:
        raise HTTPException(status_code=501, detail="summarize is not implemented in M2")

    @app.post("/v1/evaluate")
    def evaluate_stub() -> None:
        raise HTTPException(status_code=501, detail="evaluate is not implemented in M2")

    return app


def build_fallback_suggestions(request: SuggestRequest) -> SuggestResponse:
    max_suggestions = max(0, request.budget.max_suggestions)
    evidence = _evidence_from_recent_events(request)
    candidates = _candidate_targets(request)
    suggestions: list[Suggestion] = []

    for target in candidates[:max_suggestions]:
        suggestions.append(
            Suggestion(
                kind="read",
                target=target,
                confidence=0.35,
                reason="Deterministic fallback prioritized a touched or recently mentioned file.",
                evidence_ids=[item.id for item in evidence[:1]],
            )
        )

    if len(suggestions) < max_suggestions:
        query = _fallback_query(request)
        suggestions.append(
            Suggestion(
                kind="search",
                query=query,
                confidence=0.2,
                reason="No model checkpoint is available; search is a low-risk fallback action.",
                evidence_ids=[item.id for item in evidence[:1]],
            )
        )

    warnings = [
        WarningMessage(
            kind="model_unavailable",
            message=(
                "PHOTON model scoring is unavailable; deterministic fallback suggestions were used."
            ),
        )
    ]
    if not is_model_available():
        model_version = FALLBACK_MODEL_VERSION
    else:
        model_version = "photon-action-memory-v0.1.0"

    return SuggestResponse(
        request_id=request.request_id,
        schema_version=request.schema_version,
        model_version=model_version,
        suggestions=suggestions[:max_suggestions],
        evidence=evidence,
        warnings=warnings,
    )


def _candidate_targets(request: SuggestRequest) -> list[str]:
    items: list[str] = []
    touched_files = request.working_memory.get("touched_files")
    if isinstance(touched_files, list):
        items.extend(str(item) for item in touched_files if item)

    for event in request.recent_events:
        for key in ("target", "file", "path"):
            value = event.get(key)
            if isinstance(value, str) and value:
                items.append(value)

    return extract_candidates(items)


def _evidence_from_recent_events(request: SuggestRequest) -> list[EvidenceItem]:
    evidence: list[EvidenceItem] = []
    remaining_chars = max(0, request.budget.max_evidence_chars)

    for index, event in enumerate(request.recent_events, start=1):
        summary = _event_summary(event)
        if not summary:
            continue
        clipped = summary[:remaining_chars]
        if not clipped:
            break
        evidence.append(
            EvidenceItem(
                id=f"evt_{index:03d}",
                kind=str(event.get("type") or event.get("event_type") or "event"),
                summary=clipped,
                source="request",
            )
        )
        remaining_chars -= len(clipped)
        if remaining_chars <= 0:
            break

    return evidence


def _event_summary(event: dict[str, Any]) -> str:
    value = event.get("summary") or event.get("message")
    if isinstance(value, str):
        return value
    return ""


def _fallback_query(request: SuggestRequest) -> str:
    summary = request.task.get("summary") or request.task.get("user_request")
    if isinstance(summary, str) and summary:
        return summary[:120]
    return request.request_id


app = create_app()
