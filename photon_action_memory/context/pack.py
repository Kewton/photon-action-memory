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
from photon_action_memory.context.raw_policy import RawEvidenceItem, evaluate_raw_item
from photon_action_memory.context.render import estimate_tokens, render_summary

_RAW_ADMISSION_POLICY = AdmissionPolicy(raw_evidence_policy="raw_tool_log_default_deny")


def _raw_decision_id(item_id: str) -> str:
    digest = hashlib.sha256(item_id.encode()).hexdigest()[:12]
    return f"dec-raw-{digest}"


def build_context_pack(
    *,
    request_id: str,
    session_id: str | None,
    repo_id: str | None,
    summaries: list[ActionSummary],
    budget: ContextPackBudget,
    warnings: list[ContextPackWarning] | None = None,
    raw_items: list[RawEvidenceItem] | None = None,
) -> tuple[ContextPack, list[ContextAdmissionDecision]]:
    """Run the admission pipeline and return a ContextPack with decisions.

    Pure helper; can be tested without HTTP. Never raises for recoverable
    failures; callers should wrap in a try/except and set sidecar_status
    accordingly.

    Raw items are always denied under the default-deny policy and recorded
    in ``omitted``; they never appear in ``items[*].text``.
    """
    tracker = TokenBudgetTracker(max_tokens=budget.max_memory_tokens)
    controller = ContextAdmissionController(tracker)

    items: list[ContextPackItem] = []
    omitted: list[OmittedItem] = []
    decisions: list[ContextAdmissionDecision] = []

    for summary in summaries:
        decision, reason = controller.evaluate(summary)
        decisions.append(controller.make_decision(summary, decision, reason))

        if decision == "admit":
            text = render_summary(summary)
            raw_tokens = (
                summary.token_cost.estimated_raw_tokens
                if summary.token_cost
                else estimate_tokens(text) * 10
            )
            tracker.add_raw(raw_tokens)
            evidence_ids = [eid for f in summary.facts for eid in f.evidence_ids]
            items.append(
                ContextPackItem(
                    kind="action_summary",
                    id=summary.summary_id,
                    text=text,
                    evidence_ids=evidence_ids,
                    admission_reason="grounded and within budget",
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
        warnings=warnings or [],
        token_budget=tracker.to_token_budget(),
    )
    return pack, decisions


__all__ = ["build_context_pack"]
