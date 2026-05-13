"""FastAPI sidecar entrypoint."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from photon_action_memory import SCHEMA_VERSION, __version__
from photon_action_memory.api.schema import (
    DEFAULT_SCHEMA_VERSION,
    FALLBACK_MODEL_VERSION,
    EventRequest,
    EventResponse,
    EvidenceItem,
    HealthResponse,
    SidecarModel,
    SuggestRequest,
    SuggestResponse,
)
from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionSummary,
    ContextPack,
    ContextPackRequest,
    ContextPackResponse,
    ContextPackWarning,
    EvaluateRequest,
    EvaluateResponse,
    EvidenceExpandRequest,
    EvidenceExpandResponse,
    OmittedEvidence,
    SummarizeRequest,
    SummarizeResponse,
    SummaryValidateRequest,
    SummaryValidateResponse,
    TokenBudget,
)
from photon_action_memory.context.pack import build_context_pack
from photon_action_memory.context.raw_policy import RawEvidenceItem
from photon_action_memory.eval.summary_fidelity import SummaryFidelityChecker
from photon_action_memory.memory.evidence import EvidenceExpander
from photon_action_memory.memory.retrieval import SummaryRetriever
from photon_action_memory.memory.store import SQLiteEventStore
from photon_action_memory.memory.summary_store import SummaryStore
from photon_action_memory.models.photon_adapter import score_suggestions_with_optional_adapter
from photon_action_memory.ranking.fallback import build_ranked_suggestions
from photon_action_memory.ranking.guards import fallback_warnings


class SummaryUpsertRequest(SidecarModel):
    """Request body for POST /v1/summary/upsert."""

    schema_version: str
    request_id: str
    summary: ActionSummary


class SummaryUpsertResponse(SidecarModel):
    """Response body for POST /v1/summary/upsert."""

    schema_version: str
    request_id: str
    summary_id: str
    status: str


logger = logging.getLogger(__name__)


def health_payload() -> dict[str, str]:
    """Return a minimal health payload for direct client smoke checks."""
    return {"status": "ok", "schema_version": SCHEMA_VERSION}


def default_store_path() -> Path:
    configured = os.environ.get("PHOTON_ACTION_MEMORY_DB")
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "photon-action-memory" / "events.sqlite"


def default_summary_store_path() -> Path:
    configured = os.environ.get("PHOTON_ACTION_MEMORY_SUMMARY_DB")
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "photon-action-memory" / "summaries.sqlite"


def create_app(
    store: SQLiteEventStore | None = None,
    summary_store: SummaryStore | None = None,
) -> FastAPI:
    event_store = store or SQLiteEventStore(default_store_path())
    _summary_store = summary_store or SummaryStore(default_summary_store_path())
    app = FastAPI(title="PHOTON Action Memory", version=__version__)
    app.state.event_store = event_store
    app.state.summary_store = _summary_store

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

    @app.post("/v1/summary/upsert", response_model=SummaryUpsertResponse)
    def upsert_summary(request: SummaryUpsertRequest) -> SummaryUpsertResponse:
        try:
            _summary_store.upsert(request.summary)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return SummaryUpsertResponse(
            schema_version=DEFAULT_SCHEMA_VERSION_V2,
            request_id=request.request_id,
            summary_id=request.summary.summary_id,
            status="stored",
        )

    @app.post("/v1/context/pack", response_model=ContextPackResponse)
    def context_pack(request: ContextPackRequest) -> ContextPackResponse:
        try:
            route_warnings: list[ContextPackWarning] = []
            retriever = SummaryRetriever(_summary_store)
            repo_id = _context_repo_id(request)
            resolved = _resolve_context_summaries(retriever, request, repo_id=repo_id)
            raw_items = _extract_raw_items(request)
            pack, decisions = build_context_pack(
                request_id=request.request_id,
                session_id=None,
                repo_id=repo_id,
                summaries=resolved,
                budget=request.budget,
                warnings=route_warnings,
                raw_items=raw_items,
            )
            sidecar_status = "degraded" if route_warnings else "ok"
        except Exception as exc:
            empty_pack = ContextPack(
                schema_version=DEFAULT_SCHEMA_VERSION_V2,
                request_id=request.request_id,
                session_id=None,
                repo_id=None,
                mode="summary_only",
                items=[],
                omitted=[],
                warnings=[ContextPackWarning(kind="pack_error", message=str(exc))],
                token_budget=TokenBudget(
                    max_tokens=request.budget.max_memory_tokens,
                    estimated_tokens=0,
                    tokens_saved_vs_raw=0,
                ),
            )
            return ContextPackResponse(
                schema_version=DEFAULT_SCHEMA_VERSION_V2,
                request_id=request.request_id,
                model_version=FALLBACK_MODEL_VERSION,
                sidecar_status="fail-open",
                context_pack=empty_pack,
                admission_decisions=[],
            )

        return ContextPackResponse(
            schema_version=DEFAULT_SCHEMA_VERSION_V2,
            request_id=request.request_id,
            model_version=FALLBACK_MODEL_VERSION,
            sidecar_status=sidecar_status,
            context_pack=pack,
            admission_decisions=decisions,
        )

    @app.post("/v1/evidence/expand", response_model=EvidenceExpandResponse)
    def expand_evidence(request: EvidenceExpandRequest) -> EvidenceExpandResponse:
        try:
            records: list[dict[str, Any]] = [ev.payload for ev in event_store.list_events()]
            extras = request.model_extra or {}
            extra_records = extras.get("evidence_records")
            if isinstance(extra_records, list):
                records.extend(r for r in extra_records if isinstance(r, dict))
            expander = EvidenceExpander(records=records)
            return expander.expand(request)
        except Exception as exc:
            logger.warning("evidence expand error: %s", exc)
            return EvidenceExpandResponse(
                schema_version=DEFAULT_SCHEMA_VERSION_V2,
                request_id=request.request_id,
                expanded=[],
                omitted=[
                    OmittedEvidence(evidence_id=eid, reason=f"expansion error: {exc}")
                    for eid in request.evidence_ids
                ],
            )

    @app.post("/v1/summary/validate", response_model=SummaryValidateResponse)
    def validate_summary(request: SummaryValidateRequest) -> SummaryValidateResponse:
        try:
            extras = request.model_extra or {}
            raw_summaries = extras.get("summaries", [])
            summaries: list[ActionSummary] = []
            if isinstance(raw_summaries, list):
                for item in raw_summaries:
                    if isinstance(item, dict):
                        try:
                            summaries.append(ActionSummary.model_validate(item))
                        except Exception as parse_exc:
                            logger.warning("summary parse error: %s", parse_exc)

            evidence_records: list[dict[str, Any]] = []
            raw_evidence = extras.get("evidence_records")
            if isinstance(raw_evidence, list):
                evidence_records.extend(r for r in raw_evidence if isinstance(r, dict))
            evidence_records.extend(ev.payload for ev in event_store.list_events())

            checker = SummaryFidelityChecker(records=evidence_records)
            results = checker.check_all(summaries)
        except Exception as exc:
            logger.warning("summary validate error: %s", exc)
            results = []

        return SummaryValidateResponse(
            schema_version=DEFAULT_SCHEMA_VERSION_V2,
            request_id=request.request_id,
            results=results,
        )

    @app.post("/v1/summarize", response_model=SummarizeResponse)
    def summarize(request: SummarizeRequest) -> SummarizeResponse:
        return SummarizeResponse(
            schema_version=DEFAULT_SCHEMA_VERSION_V2,
            request_id=request.request_id,
            model_version=FALLBACK_MODEL_VERSION,
            sidecar_status="not_implemented",
            summary=None,
            validation=None,
            warnings=[
                ContextPackWarning(
                    kind="not_implemented",
                    message=(
                        "summarize contract is fixed in v0.4.0 P0; "
                        "generator body lands in a follow-up issue"
                    ),
                )
            ],
        )

    @app.post("/v1/evaluate", response_model=EvaluateResponse)
    def evaluate(request: EvaluateRequest) -> EvaluateResponse:
        logged = 0
        route_warnings: list[ContextPackWarning] = []
        try:
            if request.context_pack_event is not None:
                evt = request.context_pack_event
                if not evt.context_pack_request_id:
                    route_warnings.append(
                        ContextPackWarning(
                            kind="malformed_eval_input",
                            message="context_pack_request_id is empty",
                        )
                    )
                # Payload is built from named fields only; raw stdout/stderr from
                # model_extra are intentionally excluded to prevent raw output storage.
                payload: dict[str, Any] = {
                    "event_type": "context_pack_eval",
                    "session_id": request.session_id or request.request_id,
                    "turn_id": request.request_id,
                    "repo_id": "unknown",
                    "request_id": request.request_id,
                    "context_pack_request_id": evt.context_pack_request_id,
                    "adoption_status": evt.adoption_status,
                    "ignored_reason": evt.ignored_reason,
                    "evidence_expand_requested": evt.evidence_expand_requested,
                    "evidence_ids_expanded": evt.evidence_ids_expanded,
                    "items_adopted_count": evt.items_adopted_count,
                    "items_ignored_count": evt.items_ignored_count,
                    "outcome": evt.outcome,
                    "outcome_detail": evt.outcome_detail,
                    "latency_ms": evt.latency_ms,
                }
                event_store.append(payload)
                logged += 1
        except Exception as exc:
            logger.warning("evaluate log error: %s", exc)
            route_warnings.append(ContextPackWarning(kind="eval_log_error", message=str(exc)))
        return EvaluateResponse(
            schema_version=DEFAULT_SCHEMA_VERSION_V2,
            request_id=request.request_id,
            logged=logged,
            status="ok" if not route_warnings else "degraded",
            warnings=route_warnings,
        )

    return app


def _extract_raw_items(request: ContextPackRequest) -> list[RawEvidenceItem]:
    """Extract raw evidence items from request extra fields."""
    extras = request.model_extra or {}
    raw_evidence = extras.get("raw_evidence")
    if not isinstance(raw_evidence, list):
        return []
    items: list[RawEvidenceItem] = []
    for i, entry in enumerate(raw_evidence):
        if not isinstance(entry, dict):
            continue
        items.append(
            RawEvidenceItem(
                item_id=str(entry.get("item_id", f"raw-{i}")),
                kind=str(entry.get("kind", "raw_output")),
                content=str(entry.get("content", "")),
                source=str(entry["source"]) if entry.get("source") else None,
            )
        )
    return items


def _resolve_context_summaries(
    retriever: SummaryRetriever,
    request: ContextPackRequest,
    *,
    repo_id: str | None,
) -> list[ActionSummary]:
    """Resolve summaries for a context pack without falling back across repos."""
    if request.candidate_summary_ids:
        return retriever.resolve_candidates(request.candidate_summary_ids)
    if repo_id is None:
        return []

    task_signature = _context_task_signature(request)
    if task_signature is not None:
        task_matches = retriever.search(repo_id=repo_id, task_signature=task_signature)
        if task_matches:
            return task_matches
    return retriever.search(repo_id=repo_id)


def _context_repo_id(request: ContextPackRequest) -> str | None:
    """Return the repo key used for summary retrieval and response metadata."""
    if request.repo.name:
        return request.repo.name
    repo_root = request.repo.root.strip()
    if not repo_root:
        return None
    repo_name = Path(repo_root).name
    return repo_name or None


def _context_task_signature(request: ContextPackRequest) -> str | None:
    """Read an optional task_signature from forward-compatible task extras."""
    extras = request.task.model_extra or {}
    raw = extras.get("task_signature")
    if raw is None:
        return None
    task_signature = str(raw).strip()
    return task_signature or None


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
