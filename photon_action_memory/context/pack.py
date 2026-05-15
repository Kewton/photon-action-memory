"""ContextPack builder for admission and packing."""

from __future__ import annotations

import hashlib

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionSummary,
    AdmissionPolicy,
    ContextAdmissionDecision,
    ContextPack,
    ContextPackBudget,
    ContextPackItem,
    ContextPackWarning,
    OmittedItem,
)
from photon_action_memory.context.admission import ContextAdmissionController
from photon_action_memory.context.budget import TokenBudgetTracker
from photon_action_memory.context.quality_gate import evaluate_summary_quality
from photon_action_memory.context.raw_policy import RawEvidenceItem, evaluate_raw_item
from photon_action_memory.context.render import estimate_tokens, render_summary
from photon_action_memory.eval import summary_feedback as _summary_feedback_mod
from photon_action_memory.eval.summary_feedback import SummaryFeedbackRecord

_RAW_ADMISSION_POLICY = AdmissionPolicy(raw_evidence_policy="raw_tool_log_default_deny")


def _raw_decision_id(item_id: str) -> str:
    digest = hashlib.sha256(item_id.encode()).hexdigest()[:12]
    return f"dec-raw-{digest}"


def _quality_decision_id(item_id: str) -> str:
    digest = hashlib.sha256(item_id.encode()).hexdigest()[:12]
    return f"dec-quality-{digest}"


def _disabled_reason(record: SummaryFeedbackRecord) -> str:
    if record.safety_violation_count >= 1:
        return "summary disabled by feedback: safety_violation"
    return f"summary disabled by feedback: low confidence after {record.adoption_count} adoptions"


def build_context_pack(
    *,
    request_id: str,
    session_id: str | None,
    repo_id: str | None,
    summaries: list[ActionSummary],
    budget: ContextPackBudget,
    warnings: list[ContextPackWarning] | None = None,
    raw_items: list[RawEvidenceItem] | None = None,
    summary_feedback: dict[str, SummaryFeedbackRecord] | None = None,
    task_text: str | None = None,
) -> tuple[ContextPack, list[ContextAdmissionDecision]]:
    """Run the admission pipeline and return a ContextPack with decisions.

    Pure helper; can be tested without HTTP. Never raises for recoverable
    failures; callers should wrap in a try/except and set sidecar_status
    accordingly.

    Raw items are always denied under the default-deny policy and recorded
    in ``omitted``; they never appear in ``items[*].text``.

    When ``summary_feedback`` is supplied, disabled summaries are filtered
    out before admission and the remaining order is stably sorted by
    descending confidence so higher-confidence items win the token budget.
    """
    tracker = TokenBudgetTracker(max_tokens=budget.max_memory_tokens)
    controller = ContextAdmissionController(tracker)

    items: list[ContextPackItem] = []
    omitted: list[OmittedItem] = []
    decisions: list[ContextAdmissionDecision] = []
    pack_warnings = list(warnings or [])

    ordered_summaries, disabled_summaries = _apply_feedback(summaries, summary_feedback)
    for disabled_summary, disabled_reason in disabled_summaries:
        decisions.append(controller.make_decision(disabled_summary, "deny", disabled_reason))
        omitted.append(
            OmittedItem(
                kind="action_summary",
                id=disabled_summary.summary_id,
                reason=disabled_reason,
            )
        )

    for summary in ordered_summaries:
        quality = evaluate_summary_quality(summary, task_text)
        for message in quality.warnings:
            pack_warnings.append(ContextPackWarning(kind="summary_quality_gate", message=message))
        suppressed_next_hint_indices = set(quality.suppressed_next_hint_indices)
        rendered_text = render_summary(
            summary,
            exclude_next_hint_indices=suppressed_next_hint_indices,
        )
        if quality.decision == "reject" and not suppressed_next_hint_indices:
            quality_reason = quality.reason or "summary quality gate rejected"
            decisions.append(
                ContextAdmissionDecision(
                    schema_version=DEFAULT_SCHEMA_VERSION_V2,
                    decision_id=_quality_decision_id(summary.summary_id),
                    item_id=summary.summary_id,
                    item_kind="action_summary",
                    decision="deny",
                    reason=quality_reason,
                    risk=quality.risk,
                    policy=AdmissionPolicy(detail_level="summarize_quality_gate"),
                )
            )
            omitted.append(
                OmittedItem(
                    kind="action_summary",
                    id=summary.summary_id,
                    reason=quality_reason,
                )
            )
            continue

        decision, reason = controller.evaluate(summary, rendered_text=rendered_text)
        decisions.append(
            controller.make_decision(
                summary,
                decision,
                reason,
                rendered_text=rendered_text,
            )
        )

        if decision == "admit":
            raw_tokens = (
                summary.token_cost.estimated_raw_tokens
                if summary.token_cost
                else estimate_tokens(rendered_text) * 10
            )
            tracker.add_raw(raw_tokens)
            evidence_ids = [eid for f in summary.facts for eid in f.evidence_ids]
            admission_reason = "grounded and within budget"
            if suppressed_next_hint_indices:
                admission_reason += "; next_hints suppressed: premature_termination_risk"
            items.append(
                ContextPackItem(
                    kind="action_summary",
                    id=summary.summary_id,
                    text=rendered_text,
                    evidence_ids=evidence_ids,
                    admission_reason=admission_reason,
                )
            )
        else:
            omitted.append(
                OmittedItem(
                    kind="action_summary",
                    id=summary.summary_id,
                    reason=reason or "omitted",
                )
            )

    # Raw tool-log items are denied unconditionally; they must not appear in items.
    for raw_item in raw_items or []:
        _, reason = evaluate_raw_item(raw_item)
        decisions.append(
            ContextAdmissionDecision(
                schema_version=DEFAULT_SCHEMA_VERSION_V2,
                decision_id=_raw_decision_id(raw_item.item_id),
                item_id=raw_item.item_id,
                item_kind="raw_tool_log",
                decision="deny",
                reason=reason,
                policy=_RAW_ADMISSION_POLICY,
            )
        )
        omitted.append(
            OmittedItem(
                kind=raw_item.kind,
                id=raw_item.item_id,
                reason=reason,
            )
        )

    pack = ContextPack(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        request_id=request_id,
        session_id=session_id,
        repo_id=repo_id,
        mode="summary_only",
        items=items,
        omitted=omitted,
        warnings=pack_warnings,
        token_budget=tracker.to_token_budget(),
    )
    return pack, decisions


def _apply_feedback(
    summaries: list[ActionSummary],
    summary_feedback: dict[str, SummaryFeedbackRecord] | None,
) -> tuple[list[ActionSummary], list[tuple[ActionSummary, str]]]:
    """Filter disabled summaries and stably reorder by confidence."""
    if not summary_feedback:
        return list(summaries), []
    kept: list[tuple[int, float, ActionSummary]] = []
    disabled: list[tuple[ActionSummary, str]] = []
    for index, summary in enumerate(summaries):
        record = summary_feedback.get(summary.summary_id)
        if record is None:
            kept.append((index, 0.5, summary))
            continue
        if _summary_feedback_mod.is_disabled(record):
            disabled.append((summary, _disabled_reason(record)))
            continue
        kept.append((index, _summary_feedback_mod.confidence(record), summary))
    kept.sort(key=lambda triple: (-triple[1], triple[0]))
    ordered = [summary for _, _, summary in kept]
    return ordered, disabled


__all__ = ["build_context_pack"]
