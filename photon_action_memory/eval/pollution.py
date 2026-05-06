"""Context pollution metrics for v0.2 ContextPack evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from photon_action_memory.api.schema_v2 import (
    ActionSummary,
    ContextPack,
    SummaryValidationResult,
)
from photon_action_memory.context.render import estimate_tokens

POLLUTION_REPORT_SCHEMA: str = "pollution-metrics.v1"

_RAW_ITEM_KINDS: frozenset[str] = frozenset(
    {
        "stdout",
        "stderr",
        "grep_output",
        "build_log",
        "file_content",
        "raw_output",
        "tool_output",
        "raw_tool_log",
        "shell_output",
        "command_output",
    }
)
_STALE_MARKERS: tuple[str, ...] = ("stale", "contradicted")
_DUPLICATE_MARKER: str = "duplicate"


@dataclass
class PollutionRecord:
    """Per-turn context pollution measurements.

    Collect one record per context pack build and pass a list of records to
    ``build_pollution_report`` for an aggregate summary.
    """

    context_pack_tokens: int = 0
    summary_tokens_in_prompt: int = 0
    raw_tool_tokens_in_prompt: int = 0
    tokens_saved_vs_raw: int = 0
    tokens_saved_vs_full_transcript: int | None = None
    stale_summary_incidents: int = 0
    duplicate_context_incidents: int = 0
    ungrounded_fact_incidents: int = 0
    hypothesis_as_fact_incidents: int = 0
    total_summaries_evaluated: int = 0
    total_facts_evaluated: int = 0


class PollutionReport(BaseModel):
    """Aggregate-only context pollution report.

    All values are sums or rates across the input records.  No raw logs,
    prompts, or tool outputs are included.
    """

    schema_version: Literal["pollution-metrics.v1"] = "pollution-metrics.v1"
    total_records: int
    total_context_pack_tokens: int
    total_summary_tokens_in_prompt: int
    total_raw_tool_tokens_in_prompt: int
    total_tokens_saved_vs_raw: int
    tokens_saved_vs_full_transcript: int | None
    stale_summary_incidents: int
    duplicate_context_incidents: int
    ungrounded_fact_incidents: int
    hypothesis_as_fact_incidents: int
    duplicate_context_rate: float
    ungrounded_fact_rate: float
    hypothesis_as_fact_rate: float


def measure_context_pack(
    pack: ContextPack,
    *,
    summaries: list[ActionSummary] | None = None,
    validation_results: list[SummaryValidationResult] | None = None,
    full_transcript_tokens: int | None = None,
) -> PollutionRecord:
    """Compute a PollutionRecord from one ContextPack.

    ``summaries`` should be the original list passed to ``build_context_pack``
    so that ``total_facts_evaluated`` can be counted.  ``validation_results``
    should come from ``SummaryFidelityChecker.check_all`` for fidelity metrics.
    ``full_transcript_tokens`` enables savings-vs-transcript reporting.
    """
    context_pack_tokens = 0
    summary_tokens_in_prompt = 0
    raw_tool_tokens_in_prompt = 0

    for item in pack.items:
        tokens = estimate_tokens(item.text)
        context_pack_tokens += tokens
        if item.kind == "action_summary":
            summary_tokens_in_prompt += tokens
        elif item.kind in _RAW_ITEM_KINDS:
            raw_tool_tokens_in_prompt += tokens

    tokens_saved_vs_raw = pack.token_budget.tokens_saved_vs_raw or 0
    tokens_saved_vs_full_transcript: int | None = None
    if full_transcript_tokens is not None:
        tokens_saved_vs_full_transcript = max(0, full_transcript_tokens - context_pack_tokens)

    stale_summary_incidents = 0
    duplicate_context_incidents = 0
    for omitted in pack.omitted:
        reason_lower = (omitted.reason or "").lower()
        if any(m in reason_lower for m in _STALE_MARKERS):
            stale_summary_incidents += 1
        elif _DUPLICATE_MARKER in reason_lower:
            duplicate_context_incidents += 1

    ungrounded_fact_incidents = 0
    hypothesis_as_fact_incidents = 0
    for result in validation_results or []:
        for issue in result.issues:
            if issue.kind == "ungrounded_fact":
                ungrounded_fact_incidents += 1
            elif issue.kind == "hypothesis_as_fact":
                hypothesis_as_fact_incidents += 1

    total_summaries_evaluated = sum(1 for i in pack.items if i.kind == "action_summary") + sum(
        1 for o in pack.omitted if o.kind == "action_summary"
    )

    total_facts_evaluated = sum(len(s.facts) for s in (summaries or []))

    return PollutionRecord(
        context_pack_tokens=context_pack_tokens,
        summary_tokens_in_prompt=summary_tokens_in_prompt,
        raw_tool_tokens_in_prompt=raw_tool_tokens_in_prompt,
        tokens_saved_vs_raw=tokens_saved_vs_raw,
        tokens_saved_vs_full_transcript=tokens_saved_vs_full_transcript,
        stale_summary_incidents=stale_summary_incidents,
        duplicate_context_incidents=duplicate_context_incidents,
        ungrounded_fact_incidents=ungrounded_fact_incidents,
        hypothesis_as_fact_incidents=hypothesis_as_fact_incidents,
        total_summaries_evaluated=total_summaries_evaluated,
        total_facts_evaluated=total_facts_evaluated,
    )


def build_pollution_report(records: Sequence[PollutionRecord]) -> PollutionReport:
    """Aggregate a sequence of PollutionRecords into a PollutionReport."""
    if not records:
        return PollutionReport(
            total_records=0,
            total_context_pack_tokens=0,
            total_summary_tokens_in_prompt=0,
            total_raw_tool_tokens_in_prompt=0,
            total_tokens_saved_vs_raw=0,
            tokens_saved_vs_full_transcript=None,
            stale_summary_incidents=0,
            duplicate_context_incidents=0,
            ungrounded_fact_incidents=0,
            hypothesis_as_fact_incidents=0,
            duplicate_context_rate=0.0,
            ungrounded_fact_rate=0.0,
            hypothesis_as_fact_rate=0.0,
        )

    total_context_pack_tokens = sum(r.context_pack_tokens for r in records)
    total_summary_tokens_in_prompt = sum(r.summary_tokens_in_prompt for r in records)
    total_raw_tool_tokens_in_prompt = sum(r.raw_tool_tokens_in_prompt for r in records)
    total_tokens_saved_vs_raw = sum(r.tokens_saved_vs_raw for r in records)

    transcript_savings = [
        r.tokens_saved_vs_full_transcript
        for r in records
        if r.tokens_saved_vs_full_transcript is not None
    ]
    tokens_saved_vs_full_transcript: int | None = (
        sum(transcript_savings) if transcript_savings else None
    )

    stale_summary_incidents = sum(r.stale_summary_incidents for r in records)
    total_duplicate_incidents = sum(r.duplicate_context_incidents for r in records)
    total_summaries_evaluated = sum(r.total_summaries_evaluated for r in records)
    total_ungrounded_fact_incidents = sum(r.ungrounded_fact_incidents for r in records)
    total_hypothesis_as_fact_incidents = sum(r.hypothesis_as_fact_incidents for r in records)
    total_facts_evaluated = sum(r.total_facts_evaluated for r in records)

    return PollutionReport(
        total_records=len(records),
        total_context_pack_tokens=total_context_pack_tokens,
        total_summary_tokens_in_prompt=total_summary_tokens_in_prompt,
        total_raw_tool_tokens_in_prompt=total_raw_tool_tokens_in_prompt,
        total_tokens_saved_vs_raw=total_tokens_saved_vs_raw,
        tokens_saved_vs_full_transcript=tokens_saved_vs_full_transcript,
        stale_summary_incidents=stale_summary_incidents,
        duplicate_context_incidents=total_duplicate_incidents,
        ungrounded_fact_incidents=total_ungrounded_fact_incidents,
        hypothesis_as_fact_incidents=total_hypothesis_as_fact_incidents,
        duplicate_context_rate=_rate(total_duplicate_incidents, total_summaries_evaluated),
        ungrounded_fact_rate=_rate(total_ungrounded_fact_incidents, total_facts_evaluated),
        hypothesis_as_fact_rate=_rate(total_hypothesis_as_fact_incidents, total_facts_evaluated),
    )


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


__all__ = [
    "POLLUTION_REPORT_SCHEMA",
    "PollutionRecord",
    "PollutionReport",
    "build_pollution_report",
    "measure_context_pack",
]
