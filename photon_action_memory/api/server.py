"""FastAPI sidecar entrypoint."""

from __future__ import annotations

import logging
import os
import re
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
    ActionChunk,
    ActionSummary,
    AdmissionPolicy,
    ContextAdmissionDecision,
    ContextPack,
    ContextPackRequest,
    ContextPackResponse,
    ContextPackWarning,
    EvaluateRequest,
    EvaluateResponse,
    EvidenceExpandRequest,
    EvidenceExpandResponse,
    OmittedEvidence,
    OmittedItem,
    SummarizeRequest,
    SummarizeResponse,
    SummaryValidateRequest,
    SummaryValidateResponse,
    SummaryValidationIssue,
    SummaryValidationResult,
    TokenBudget,
    TokenCost,
    UniversalFilters,
)
from photon_action_memory.context.pack import build_context_pack
from photon_action_memory.context.raw_policy import (
    RawEvidenceItem,
    evaluate_raw_item,
    has_sensitive_content,
)
from photon_action_memory.context.render import estimate_tokens, render_summary
from photon_action_memory.eval.summary_fidelity import SummaryFidelityChecker
from photon_action_memory.memory.chunks import ActionChunker
from photon_action_memory.memory.evidence import EvidenceExpander
from photon_action_memory.memory.retrieval import (
    SummaryRetriever,
    merge_dedup_summaries,
)
from photon_action_memory.memory.sanitizer import sanitize_text_with_report
from photon_action_memory.memory.store import SQLiteEventStore
from photon_action_memory.memory.summaries import (
    ActionSummaryBuilder,
    SummaryCanonicalizer,
    SummaryStateUpdater,
)
from photon_action_memory.memory.summary_store import SummaryStore
from photon_action_memory.models.photon_adapter import score_suggestions_with_optional_adapter
from photon_action_memory.ranking.fallback import build_ranked_suggestions
from photon_action_memory.ranking.guards import fallback_warnings

_UNIVERSAL_MAX_ITEMS = 5
_UNIVERSAL_MAX_TOKENS = 500


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
            feedback_map = _summary_store.get_feedback_map([s.summary_id for s in resolved])
            pack, decisions = build_context_pack(
                request_id=request.request_id,
                session_id=None,
                repo_id=repo_id,
                summaries=resolved,
                budget=request.budget,
                warnings=route_warnings,
                raw_items=raw_items,
                summary_feedback=feedback_map,
                task_text=_context_task_text(request),
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
        if request.draft_summary is not None:
            return _summarize_with_firewall(request, event_store=event_store)
        if "chunks" in request.model_fields_set:
            return _summarize_inline_chunks(request, event_store, _summary_store)

        try:
            repo_id = request.repo_id
            if repo_id is None and request.repo is not None:
                repo_id = request.repo.name
            task_signature = request.task_signature
            if task_signature is None and request.task is not None:
                task_signature = request.task.summary or request.task.user_request

            stored_events = event_store.list_events(
                session_id=request.session_id,
                repo_id=repo_id,
            )
            chunks = ActionChunker().chunk(stored_events)
            builder = ActionSummaryBuilder()
            canonicalizer = SummaryCanonicalizer()
            summaries: list[ActionSummary] = []
            summary_ids: list[str] = []
            for chunk in chunks:
                summary = builder.build(chunk)
                if task_signature is not None:
                    summary = summary.model_copy(update={"task_signature": task_signature})
                summary = canonicalizer.canonicalize(summary).summary
                _summary_store.upsert(summary)
                summaries.append(summary)
                summary_ids.append(summary.summary_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return SummarizeResponse(
            schema_version=DEFAULT_SCHEMA_VERSION_V2,
            request_id=request.request_id,
            model_version=FALLBACK_MODEL_VERSION,
            sidecar_status="ok",
            status="ok",
            chunks_built=len(chunks),
            summaries_upserted=len(summary_ids),
            summary_ids=summary_ids,
            summary=summaries[0] if summaries else None,
            validation=None,
            tokens_saved_vs_raw=sum(_tokens_saved(summary.token_cost) for summary in summaries),
            warnings=[],
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
                    "summary_ids_adopted": evt.summary_ids_adopted,
                }
                event_store.append(payload)
                logged += 1
                if evt.summary_ids_adopted:
                    try:
                        _summary_store.record_outcomes(
                            evt.summary_ids_adopted,
                            adoption_status=evt.adoption_status,
                            outcome=evt.outcome,
                            evidence_expand_requested=evt.evidence_expand_requested,
                        )
                    except Exception as exc:
                        logger.warning("summary feedback record error: %s", exc)
                        route_warnings.append(
                            ContextPackWarning(
                                kind="summary_feedback_error",
                                message=str(exc),
                            )
                        )
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


def _summarize_inline_chunks(
    request: SummarizeRequest,
    event_store: SQLiteEventStore,
    summary_store: SummaryStore,
) -> SummarizeResponse:
    warnings: list[ContextPackWarning] = []
    try:
        summary = _build_hierarchical_summary(request)
    except ValueError as exc:
        return SummarizeResponse(
            schema_version=DEFAULT_SCHEMA_VERSION_V2,
            request_id=request.request_id,
            model_version=FALLBACK_MODEL_VERSION,
            sidecar_status="degraded",
            status="degraded",
            chunks_built=0,
            summaries_upserted=0,
            summary_ids=[],
            summary=None,
            validation=None,
            tokens_saved_vs_raw=0,
            warnings=[ContextPackWarning(kind="summarize_input", message=str(exc))],
        )

    try:
        evidence_records = [ev.payload for ev in event_store.list_events()]
        checker = SummaryFidelityChecker(records=evidence_records)
        validation = checker.check(summary)
    except Exception as exc:
        logger.warning("summarize fidelity error: %s", exc)
        validation = None
        warnings.append(ContextPackWarning(kind="summarize_validation_error", message=str(exc)))

    summary_ids: list[str] = []
    summaries_upserted = 0
    try:
        summary_store.upsert(summary)
        summary_ids.append(summary.summary_id)
        summaries_upserted = 1
    except Exception as exc:
        logger.warning("summarize persist error: %s", exc)
        warnings.append(ContextPackWarning(kind="summarize_persist_error", message=str(exc)))

    return SummarizeResponse(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        request_id=request.request_id,
        model_version=FALLBACK_MODEL_VERSION,
        sidecar_status="degraded" if warnings else "ok",
        status="degraded" if warnings else "ok",
        chunks_built=len(request.chunks),
        summaries_upserted=summaries_upserted,
        summary_ids=summary_ids,
        summary=summary,
        validation=validation,
        tokens_saved_vs_raw=_tokens_saved(summary.token_cost),
        warnings=warnings,
    )


def _tokens_saved(token_cost: TokenCost | None) -> int:
    if token_cost is None:
        return 0
    return max(0, token_cost.tokens_saved_vs_raw)


def _build_hierarchical_summary(request: SummarizeRequest) -> ActionSummary:
    """Fold request chunks into a single ActionSummary at the requested level."""
    chunks: list[ActionChunk] = list(request.chunks)
    if not chunks:
        msg = "summarize requires at least one chunk"
        raise ValueError(msg)

    builder = ActionSummaryBuilder()
    canonicalizer = SummaryCanonicalizer()
    updater = SummaryStateUpdater()

    state = canonicalizer.canonicalize(builder.build(chunks[0])).summary
    for chunk in chunks[1:]:
        state = updater.update(state, chunk)

    overrides: dict[str, object] = {"summary_level": request.summary_level}
    if request.session_id is not None:
        overrides["session_id"] = request.session_id
    if request.repo_id is not None:
        overrides["repo_id"] = request.repo_id
    if request.task_signature is not None:
        overrides["task_signature"] = request.task_signature
    if request.summary_id:
        overrides["summary_id"] = request.summary_id
    return state.model_copy(update=overrides)


_SUMMARIZE_RAW_POLICY_NAME = "raw_tool_log_default_deny"


def _summarize_with_firewall(
    request: SummarizeRequest,
    *,
    event_store: SQLiteEventStore,
) -> SummarizeResponse:
    """Apply the Action Context Firewall to a draft ActionSummary.

    1) Redact secrets / home paths / token-like strings from prompt-visible
       fields so they cannot reach a downstream ContextPack.
    2) Deny any raw_evidence under the existing default-deny policy.
    3) Run SummaryFidelityChecker so the caller can see grounding / raw
       leakage signals in ``validation_results``.
    4) Surface ``evidence_ids_referenced`` so the caller can follow up with
       /v1/evidence/expand for redacted snippets on demand.
    """
    draft = request.draft_summary
    if draft is None:
        raise ValueError("draft_summary is required for summarize firewall mode")
    try:
        extras = request.model_extra or {}
        evidence_records: list[dict[str, Any]] = []
        raw_evidence_extra = extras.get("evidence_records")
        if isinstance(raw_evidence_extra, list):
            evidence_records.extend(r for r in raw_evidence_extra if isinstance(r, dict))
        evidence_records.extend(ev.payload for ev in event_store.list_events())

        raw_items = _coerce_summarize_raw_items(extras.get("raw_evidence"))

        firewalled, leakage_redactions = _apply_summary_firewall(draft)
        checker = SummaryFidelityChecker(records=evidence_records)
        result = checker.check(firewalled)

        if leakage_redactions:
            extra_issues = list(result.issues) + [
                SummaryValidationIssue(
                    kind="raw_output_in_field",
                    message=msg,
                )
                for msg in leakage_redactions
            ]
            result = result.model_copy(
                update={
                    "issues": extra_issues,
                    "status": "invalid",
                }
            )

        admission_decisions, omitted = _deny_summarize_raw_evidence(raw_items)
        evidence_ids = _collect_summary_evidence_ids(firewalled)

        return SummarizeResponse(
            schema_version=DEFAULT_SCHEMA_VERSION_V2,
            request_id=request.request_id,
            model_version=FALLBACK_MODEL_VERSION,
            sidecar_status="ok",
            status="ok",
            chunks_built=0,
            summaries_upserted=0,
            summary_ids=[firewalled.summary_id],
            summary=firewalled,
            validation=result,
            tokens_saved_vs_raw=_tokens_saved(firewalled.token_cost),
            warnings=[],
            validation_results=[result],
            admission_decisions=admission_decisions,
            omitted=omitted,
            evidence_ids_referenced=evidence_ids,
        )
    except Exception as exc:
        logger.warning("summarize firewall error: %s", exc)
        fallback_issue = SummaryValidationIssue(
            kind="summarize_error",
            message=f"summarize firewall error: {exc}",
        )
        fallback_result = SummaryValidationResult(
            summary_id=draft.summary_id,
            status="invalid",
            score=0.0,
            issues=[fallback_issue],
        )
        return SummarizeResponse(
            schema_version=DEFAULT_SCHEMA_VERSION_V2,
            request_id=request.request_id,
            model_version=FALLBACK_MODEL_VERSION,
            sidecar_status="degraded",
            status="degraded",
            chunks_built=0,
            summaries_upserted=0,
            summary_ids=[draft.summary_id],
            summary=draft,
            validation=fallback_result,
            tokens_saved_vs_raw=_tokens_saved(draft.token_cost),
            warnings=[ContextPackWarning(kind="summarize_error", message=str(exc))],
            validation_results=[fallback_result],
            admission_decisions=[],
            omitted=[],
            evidence_ids_referenced=[],
        )


def _coerce_summarize_raw_items(raw: object) -> list[RawEvidenceItem]:
    if not isinstance(raw, list):
        return []
    items: list[RawEvidenceItem] = []
    for i, entry in enumerate(raw):
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


def _deny_summarize_raw_evidence(
    raw_items: list[RawEvidenceItem],
) -> tuple[list[ContextAdmissionDecision], list[OmittedItem]]:
    decisions: list[ContextAdmissionDecision] = []
    omitted: list[OmittedItem] = []
    for raw_item in raw_items:
        _, reason = evaluate_raw_item(raw_item)
        decisions.append(
            ContextAdmissionDecision(
                schema_version=DEFAULT_SCHEMA_VERSION_V2,
                decision_id=f"dec-summ-{raw_item.item_id}",
                item_id=raw_item.item_id,
                item_kind="raw_tool_log",
                decision="deny",
                reason=reason,
                policy=AdmissionPolicy(raw_evidence_policy=_SUMMARIZE_RAW_POLICY_NAME),
            )
        )
        omitted.append(
            OmittedItem(
                kind=raw_item.kind,
                id=raw_item.item_id,
                reason=reason,
            )
        )
    return decisions, omitted


def _apply_summary_firewall(summary: ActionSummary) -> tuple[ActionSummary, list[str]]:
    """Redact secrets in every prompt-visible string field of a draft summary.

    Returns the redacted summary and a list of messages describing which fields
    were redacted (one per affected field), suitable for surfacing as
    ``raw_output_in_field`` issues alongside the checker's own findings.
    """
    redactions: list[str] = []

    def _scrub(value: str | None, where: str) -> str | None:
        if not value or not has_sensitive_content(value):
            return value
        cleaned = sanitize_text_with_report(value).text
        redactions.append(f"{where} contained raw output / secret / home path; redacted")
        return cleaned

    new_facts = [
        fact.model_copy(update={"text": _scrub(fact.text, f"facts[{i}].text") or ""})
        for i, fact in enumerate(summary.facts)
    ]
    new_hypotheses = [
        hyp.model_copy(update={"text": _scrub(hyp.text, f"hypotheses[{i}].text") or ""})
        for i, hyp in enumerate(summary.hypotheses)
    ]
    new_failed = [
        fa.model_copy(
            update={
                "action": _scrub(fa.action, f"failed_attempts[{i}].action") or "",
                "outcome": _scrub(fa.outcome, f"failed_attempts[{i}].outcome") or "",
            }
        )
        for i, fa in enumerate(summary.failed_attempts)
    ]
    new_avoid = [
        av.model_copy(
            update={
                "action": _scrub(av.action, f"avoid[{i}].action") or "",
                "reason": _scrub(av.reason, f"avoid[{i}].reason") or "",
            }
        )
        for i, av in enumerate(summary.avoid)
    ]
    new_actions_done = [
        ad.model_copy(
            update={
                "target": _scrub(ad.target, f"actions_done[{i}].target"),
                "command": _scrub(ad.command, f"actions_done[{i}].command"),
                "outcome": _scrub(ad.outcome, f"actions_done[{i}].outcome") or "",
            }
        )
        for i, ad in enumerate(summary.actions_done)
    ]
    new_next_hints = [
        nh.model_copy(
            update={
                "target": _scrub(nh.target, f"next_hints[{i}].target"),
                "reason": _scrub(nh.reason, f"next_hints[{i}].reason") or "",
            }
        )
        for i, nh in enumerate(summary.next_hints)
    ]
    new_validity = summary.validity
    if summary.validity and summary.validity.reason:
        cleaned = _scrub(summary.validity.reason, "validity.reason")
        if cleaned != summary.validity.reason:
            new_validity = summary.validity.model_copy(update={"reason": cleaned})

    firewalled = summary.model_copy(
        update={
            "facts": new_facts,
            "hypotheses": new_hypotheses,
            "failed_attempts": new_failed,
            "avoid": new_avoid,
            "actions_done": new_actions_done,
            "next_hints": new_next_hints,
            "validity": new_validity,
        }
    )
    return firewalled, redactions


def _collect_summary_evidence_ids(summary: ActionSummary) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    sources = (
        summary.facts,
        summary.hypotheses,
        summary.failed_attempts,
        summary.avoid,
        summary.actions_done,
    )
    for group in sources:
        for item in group:
            for eid in getattr(item, "evidence_ids", []) or []:
                if eid and eid not in seen:
                    seen.add(eid)
                    ordered.append(eid)
    return ordered


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
    """Resolve summaries with repo-specific results before common seed fallback."""
    if request.candidate_summary_ids:
        return retriever.resolve_candidates(request.candidate_summary_ids)

    task_signature = _context_task_signature(request)
    results: list[ActionSummary] = []
    if repo_id is not None and task_signature is not None:
        task_matches = retriever.search(repo_id=repo_id, task_signature=task_signature)
        if task_matches:
            results = merge_dedup_summaries(results, task_matches)
    if repo_id is not None and not results:
        results = merge_dedup_summaries(results, retriever.search(repo_id=repo_id))
    if task_signature is not None:
        results = merge_dedup_summaries(
            results,
            retriever.search_common(task_signature=task_signature),
        )
    universal = _select_universal_summaries(
        retriever.search_universal(filters=detect_universal_filters(request))
    )
    results = merge_dedup_summaries(results, universal)
    return results


def detect_universal_filters(request: ContextPackRequest) -> UniversalFilters:
    """Detect language/framework/tool/os filters for universal seed retrieval."""
    text = _universal_detection_text(request)
    touched = " ".join(request.working_memory.touched_files)
    return UniversalFilters(
        language=sorted(_detect_languages(text, touched)),
        framework=sorted(_detect_frameworks(text, touched)),
        tool=sorted(_detect_tools(text, touched)),
        os=sorted(_detect_operating_systems(text)),
    )


def _universal_detection_text(request: ContextPackRequest) -> str:
    parts = [
        request.task.user_request,
        request.task.summary or "",
        request.working_memory.active_task or "",
        " ".join(request.working_memory.constraints),
        " ".join(request.working_memory.unresolved_errors),
        " ".join(request.working_memory.notes),
        " ".join(request.working_memory.touched_files),
    ]
    return "\n".join(part for part in parts if part).lower()


def _detect_languages(text: str, touched_files: str) -> set[str]:
    languages: set[str] = set()
    markers = {
        "python": ("python", "pytest", "pydantic", "fastapi", ".py"),
        "rust": ("rust", "cargo", "clippy", ".rs"),
        "javascript": ("javascript", "node", "npm", "pnpm", ".js", ".jsx"),
        "typescript": ("typescript", "tsconfig", ".ts", ".tsx"),
        "svelte": ("svelte", "sveltekit", ".svelte"),
    }
    haystack = f"{text}\n{touched_files.lower()}"
    for language, needles in markers.items():
        if any(needle in haystack for needle in needles):
            languages.add(language)
    return languages


def _detect_frameworks(text: str, touched_files: str) -> set[str]:
    frameworks: set[str] = set()
    haystack = f"{text}\n{touched_files.lower()}"
    markers = {
        "pytest": ("pytest",),
        "fastapi": ("fastapi",),
        "pydantic": ("pydantic",),
        "sveltekit": ("sveltekit", ".svelte", "src/routes"),
        "react": ("react", ".jsx", ".tsx"),
        "nextjs": ("next.js", "nextjs"),
    }
    for framework, needles in markers.items():
        if any(needle in haystack for needle in needles):
            frameworks.add(framework)
    return frameworks


def _detect_tools(text: str, touched_files: str) -> set[str]:
    tools: set[str] = set()
    haystack = f"{text}\n{touched_files.lower()}"
    markers = {
        "git": ("git", ".git", "commit", "worktree"),
        "pytest": ("pytest",),
        "cargo": ("cargo", "clippy"),
        "npm": ("npm", "package.json"),
        "pnpm": ("pnpm", "pnpm-lock.yaml"),
        "node": ("node", "package.json", ".js", ".ts", ".svelte"),
    }
    for tool, needles in markers.items():
        if any(needle in haystack for needle in needles):
            tools.add(tool)
    return tools


def _detect_operating_systems(text: str) -> set[str]:
    systems: set[str] = set()
    markers = {
        "darwin": ("macos", "mac os", "darwin", "mlx"),
        "linux": ("linux", "ubuntu", "debian"),
        "windows": ("windows", "powershell", "win32"),
    }
    for system, needles in markers.items():
        if any(re.search(rf"\b{re.escape(needle)}\b", text) for needle in needles):
            systems.add(system)
    return systems


def _select_universal_summaries(summaries: list[ActionSummary]) -> list[ActionSummary]:
    selected: list[ActionSummary] = []
    total_tokens = 0
    for summary in summaries:
        if len(selected) >= _UNIVERSAL_MAX_ITEMS:
            break
        tokens = estimate_tokens(render_summary(summary))
        metadata = summary.universal_metadata
        per_seed_cap = metadata.token_budget_cap if metadata is not None else 100
        if tokens > per_seed_cap:
            continue
        if total_tokens + tokens > _UNIVERSAL_MAX_TOKENS:
            continue
        selected.append(summary)
        total_tokens += tokens
    return selected


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


def _context_task_text(request: ContextPackRequest) -> str:
    """Return task text used by task-aware ContextPack quality gates."""
    parts = [request.task.user_request]
    if request.task.summary:
        parts.append(request.task.summary)
    return "\n".join(part for part in parts if part)


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
