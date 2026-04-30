"""FastAPI sidecar entrypoint."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException

from photon_action_memory import SCHEMA_VERSION, __version__
from photon_action_memory.api.schema import (
    DEFAULT_SCHEMA_VERSION,
    FALLBACK_MODEL_VERSION,
    EventRequest,
    EventResponse,
    EvidenceItem,
    HealthResponse,
    SuggestRequest,
    SuggestResponse,
)
from photon_action_memory.memory.store import SQLiteEventStore
from photon_action_memory.models.photon_adapter import score_suggestions_with_optional_adapter
from photon_action_memory.ranking.fallback import build_ranked_suggestions
from photon_action_memory.ranking.guards import fallback_warnings


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
        return HealthResponse(status="ok", schema_version=DEFAULT_SCHEMA_VERSION)

    @app.post("/v1/events", response_model=EventResponse)
    def append_event(event: EventRequest) -> EventResponse:
        stored_events = []
        for item in event.events:
            payload = item.model_dump(mode="json")
            payload["turn_id"] = payload.get("turn_id") or event.request_id
            payload["repo_id"] = payload.get("repo_id") or "unknown"
            stored_events.append(event_store.append(payload))
        stored = stored_events[-1]
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
    fallback_suggestions = build_ranked_suggestions(
        request,
        evidence=evidence,
        limit=max_suggestions,
    )
    adapter_result = score_suggestions_with_optional_adapter(
        request,
        evidence=evidence,
        suggestions=fallback_suggestions,
    )
    if adapter_result is None:
        suggestions = fallback_suggestions
        model_version = FALLBACK_MODEL_VERSION
        warnings = fallback_warnings(request)
    else:
        suggestions, model_version = adapter_result
        warnings = []

    return SuggestResponse(
        request_id=request.request_id,
        schema_version=request.schema_version,
        model_version=model_version,
        suggestions=suggestions[:max_suggestions],
        evidence=evidence,
        warnings=warnings,
    )


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
                kind=event.type,
                summary=clipped,
                source="request",
            )
        )
        remaining_chars -= len(clipped)
        if remaining_chars <= 0:
            break

    return evidence


def _event_summary(event: object) -> str:
    return str(getattr(event, "summary", "") or "")


app = create_app()
