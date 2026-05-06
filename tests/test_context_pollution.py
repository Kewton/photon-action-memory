"""Tests for context pollution metrics (issue #41)."""

from __future__ import annotations

import pytest

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionSummary,
    ContextPackBudget,
    Fact,
    Hypothesis,
    SummaryValidationIssue,
    SummaryValidationResult,
    TokenCost,
    Validity,
)
from photon_action_memory.context.pack import build_context_pack
from photon_action_memory.context.raw_policy import RawEvidenceItem
from photon_action_memory.eval.pollution import (
    PollutionRecord,
    build_pollution_report,
    measure_context_pack,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fact(text: str, evidence_id: str = "ev-1") -> Fact:
    return Fact(text=text, evidence_ids=[evidence_id], confidence=0.9)


def _hypothesis(text: str) -> Hypothesis:
    return Hypothesis(text=text, evidence_ids=["ev-1"], confidence=0.5)


def _summary(
    summary_id: str,
    facts: list[Fact] | None = None,
    hypotheses: list[Hypothesis] | None = None,
    validity_status: str = "valid",
    token_cost: TokenCost | None = None,
) -> ActionSummary:
    return ActionSummary(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        summary_id=summary_id,
        facts=facts or [],
        hypotheses=hypotheses or [],
        validity=Validity(status=validity_status),
        token_cost=token_cost,
    )


def _raw(item_id: str, kind: str = "stdout", content: str = "raw output") -> RawEvidenceItem:
    return RawEvidenceItem(item_id=item_id, kind=kind, content=content)


def _pack_with(
    summaries: list[ActionSummary] | None = None,
    raw_items: list[RawEvidenceItem] | None = None,
    max_tokens: int = 800,
) -> tuple:  # type: ignore[type-arg]
    return build_context_pack(
        request_id="req-test",
        session_id=None,
        repo_id=None,
        summaries=summaries or [],
        budget=ContextPackBudget(max_memory_tokens=max_tokens),
        raw_items=raw_items,
    )


def _validation_issue(kind: str, message: str = "issue") -> SummaryValidationIssue:
    return SummaryValidationIssue(kind=kind, message=message)


def _validation_result(
    summary_id: str,
    issues: list[SummaryValidationIssue],
) -> SummaryValidationResult:
    return SummaryValidationResult(
        summary_id=summary_id,
        status="invalid" if issues else "valid",
        score=0.5,
        issues=issues,
    )


# ---------------------------------------------------------------------------
# measure_context_pack - token measurements
# ---------------------------------------------------------------------------


def test_empty_pack_yields_zero_tokens() -> None:
    pack, _ = _pack_with()
    record = measure_context_pack(pack)
    assert record.context_pack_tokens == 0
    assert record.summary_tokens_in_prompt == 0
    assert record.raw_tool_tokens_in_prompt == 0
    assert record.tokens_saved_vs_raw == 0
    assert record.tokens_saved_vs_full_transcript is None


def test_admitted_summary_tokens_counted() -> None:
    summaries = [_summary("s-1", facts=[_fact("the thing is done")])]
    pack, _ = _pack_with(summaries=summaries)
    record = measure_context_pack(pack)
    assert record.summary_tokens_in_prompt > 0
    assert record.context_pack_tokens == record.summary_tokens_in_prompt


def test_tokens_saved_vs_raw_from_budget() -> None:
    tc = TokenCost(estimated_summary_tokens=10, estimated_raw_tokens=100, tokens_saved_vs_raw=90)
    s = _summary("s-tc", facts=[_fact("some fact")], token_cost=tc)
    pack, _ = _pack_with(summaries=[s])
    record = measure_context_pack(pack)
    assert record.tokens_saved_vs_raw >= 0


def test_tokens_saved_vs_full_transcript_computed() -> None:
    summaries = [_summary("s-1", facts=[_fact("fact")])]
    pack, _ = _pack_with(summaries=summaries)
    record = measure_context_pack(pack, full_transcript_tokens=1000)
    assert record.tokens_saved_vs_full_transcript == max(0, 1000 - record.context_pack_tokens)


def test_tokens_saved_vs_full_transcript_none_when_not_provided() -> None:
    pack, _ = _pack_with()
    record = measure_context_pack(pack)
    assert record.tokens_saved_vs_full_transcript is None


def test_tokens_saved_vs_full_transcript_non_negative() -> None:
    summaries = [_summary("s-1", facts=[_fact("f")])]
    pack, _ = _pack_with(summaries=summaries)
    record = measure_context_pack(pack, full_transcript_tokens=0)
    assert record.tokens_saved_vs_full_transcript == 0


# ---------------------------------------------------------------------------
# measure_context_pack - raw-tool-deny policy fixture
# ---------------------------------------------------------------------------


def test_raw_tool_deny_policy_keeps_raw_tokens_at_zero() -> None:
    """Fixture: default raw-tool-deny policy must keep raw_tool_tokens_in_prompt == 0."""
    raw_items = [
        _raw(f"r-{i}", kind, "x" * 2000)
        for i, kind in enumerate(["stdout", "stderr", "grep_output", "build_log", "file_content"])
    ]
    pack, _ = _pack_with(raw_items=raw_items)
    record = measure_context_pack(pack)
    assert record.raw_tool_tokens_in_prompt == 0


def test_raw_tokens_zero_with_mixed_summaries_and_raw() -> None:
    """Raw items must not contribute tokens even when summaries are also present."""
    summaries = [_summary("s-1", facts=[_fact("server lives in api/")])]
    raw_items = [_raw("r-1", "stdout", "cargo build output " * 50)]
    pack, _ = _pack_with(summaries=summaries, raw_items=raw_items)
    record = measure_context_pack(pack)
    assert record.raw_tool_tokens_in_prompt == 0
    assert record.summary_tokens_in_prompt > 0


# ---------------------------------------------------------------------------
# measure_context_pack - incident detection
# ---------------------------------------------------------------------------


def test_stale_summary_incidents_counted() -> None:
    stale = _summary("s-stale", facts=[_fact("old fact")], validity_status="stale")
    valid = _summary("s-valid", facts=[_fact("current fact")])
    pack, _ = _pack_with(summaries=[stale, valid])
    record = measure_context_pack(pack)
    assert record.stale_summary_incidents == 1


def test_contradicted_summary_counted_as_stale_incident() -> None:
    contradicted = _summary("s-contra", facts=[_fact("wrong")], validity_status="contradicted")
    pack, _ = _pack_with(summaries=[contradicted])
    record = measure_context_pack(pack)
    assert record.stale_summary_incidents == 1


def test_duplicate_context_incidents_counted() -> None:
    facts = [_fact("same fact text")]
    s1 = _summary("s-1", facts=facts)
    s2 = _summary("s-2", facts=facts)
    pack, _ = _pack_with(summaries=[s1, s2])
    record = measure_context_pack(pack)
    assert record.duplicate_context_incidents == 1


def test_ungrounded_fact_incidents_from_validation_results() -> None:
    vr = _validation_result(
        "s-1",
        [
            _validation_issue("ungrounded_fact", "no evidence"),
            _validation_issue("ungrounded_fact", "another missing"),
        ],
    )
    pack, _ = _pack_with()
    record = measure_context_pack(pack, validation_results=[vr])
    assert record.ungrounded_fact_incidents == 2


def test_hypothesis_as_fact_incidents_from_validation_results() -> None:
    vr = _validation_result(
        "s-1",
        [_validation_issue("hypothesis_as_fact", "uncertainty language detected")],
    )
    pack, _ = _pack_with()
    record = measure_context_pack(pack, validation_results=[vr])
    assert record.hypothesis_as_fact_incidents == 1


def test_no_incidents_when_no_validation_results() -> None:
    pack, _ = _pack_with()
    record = measure_context_pack(pack)
    assert record.ungrounded_fact_incidents == 0
    assert record.hypothesis_as_fact_incidents == 0


# ---------------------------------------------------------------------------
# measure_context_pack - totals
# ---------------------------------------------------------------------------


def test_total_facts_evaluated_from_summaries() -> None:
    summaries = [
        _summary("s-1", facts=[_fact("f1"), _fact("f2")]),
        _summary("s-2", facts=[_fact("f3")]),
    ]
    pack, _ = _pack_with(summaries=summaries)
    record = measure_context_pack(pack, summaries=summaries)
    assert record.total_facts_evaluated == 3


def test_total_summaries_evaluated_includes_omitted() -> None:
    stale = _summary("s-stale", facts=[_fact("old")], validity_status="stale")
    valid = _summary("s-valid", facts=[_fact("new")])
    pack, _ = _pack_with(summaries=[stale, valid])
    record = measure_context_pack(pack)
    assert record.total_summaries_evaluated == 2


def test_total_facts_zero_when_no_summaries_passed() -> None:
    pack, _ = _pack_with()
    record = measure_context_pack(pack)
    assert record.total_facts_evaluated == 0


# ---------------------------------------------------------------------------
# build_pollution_report - aggregation
# ---------------------------------------------------------------------------


def test_empty_records_yields_zero_report() -> None:
    report = build_pollution_report([])
    assert report.total_records == 0
    assert report.total_context_pack_tokens == 0
    assert report.total_raw_tool_tokens_in_prompt == 0
    assert report.stale_summary_incidents == 0
    assert report.duplicate_context_incidents == 0
    assert report.ungrounded_fact_incidents == 0
    assert report.hypothesis_as_fact_incidents == 0
    assert report.duplicate_context_rate == 0.0
    assert report.ungrounded_fact_rate == 0.0
    assert report.hypothesis_as_fact_rate == 0.0


def test_aggregate_tokens_summed() -> None:
    r1 = PollutionRecord(context_pack_tokens=100, summary_tokens_in_prompt=100)
    r2 = PollutionRecord(context_pack_tokens=50, summary_tokens_in_prompt=50)
    report = build_pollution_report([r1, r2])
    assert report.total_context_pack_tokens == 150
    assert report.total_summary_tokens_in_prompt == 150


def test_stale_incidents_summed() -> None:
    r1 = PollutionRecord(stale_summary_incidents=2, total_summaries_evaluated=5)
    r2 = PollutionRecord(stale_summary_incidents=1, total_summaries_evaluated=3)
    report = build_pollution_report([r1, r2])
    assert report.stale_summary_incidents == 3


def test_duplicate_context_rate_computed() -> None:
    r1 = PollutionRecord(duplicate_context_incidents=1, total_summaries_evaluated=4)
    r2 = PollutionRecord(duplicate_context_incidents=1, total_summaries_evaluated=4)
    report = build_pollution_report([r1, r2])
    assert report.duplicate_context_incidents == 2
    assert report.duplicate_context_rate == pytest.approx(2 / 8)


def test_ungrounded_fact_rate_computed() -> None:
    r1 = PollutionRecord(ungrounded_fact_incidents=2, total_facts_evaluated=10)
    r2 = PollutionRecord(ungrounded_fact_incidents=1, total_facts_evaluated=5)
    report = build_pollution_report([r1, r2])
    assert report.ungrounded_fact_incidents == 3
    assert report.ungrounded_fact_rate == pytest.approx(3 / 15)


def test_hypothesis_as_fact_rate_computed() -> None:
    r1 = PollutionRecord(hypothesis_as_fact_incidents=1, total_facts_evaluated=5)
    report = build_pollution_report([r1])
    assert report.hypothesis_as_fact_incidents == 1
    assert report.hypothesis_as_fact_rate == pytest.approx(1 / 5)


def test_rates_zero_when_no_facts_evaluated() -> None:
    r1 = PollutionRecord(ungrounded_fact_incidents=0, total_facts_evaluated=0)
    report = build_pollution_report([r1])
    assert report.ungrounded_fact_rate == 0.0
    assert report.hypothesis_as_fact_rate == 0.0


def test_rates_zero_when_no_summaries_evaluated() -> None:
    r1 = PollutionRecord(duplicate_context_incidents=0, total_summaries_evaluated=0)
    report = build_pollution_report([r1])
    assert report.duplicate_context_rate == 0.0


def test_tokens_saved_vs_full_transcript_aggregated() -> None:
    r1 = PollutionRecord(tokens_saved_vs_full_transcript=100)
    r2 = PollutionRecord(tokens_saved_vs_full_transcript=200)
    report = build_pollution_report([r1, r2])
    assert report.tokens_saved_vs_full_transcript == 300


def test_tokens_saved_vs_full_transcript_none_when_all_none() -> None:
    r1 = PollutionRecord()
    r2 = PollutionRecord()
    report = build_pollution_report([r1, r2])
    assert report.tokens_saved_vs_full_transcript is None


def test_tokens_saved_vs_full_transcript_partial_some_none() -> None:
    r1 = PollutionRecord(tokens_saved_vs_full_transcript=50)
    r2 = PollutionRecord(tokens_saved_vs_full_transcript=None)
    report = build_pollution_report([r1, r2])
    assert report.tokens_saved_vs_full_transcript == 50


# ---------------------------------------------------------------------------
# build_pollution_report - report shape and safety
# ---------------------------------------------------------------------------


def test_report_is_aggregate_only() -> None:
    """Reports must be aggregate-only with no raw logs, prompts, or tool outputs."""
    r1 = PollutionRecord(context_pack_tokens=100, stale_summary_incidents=1)
    report = build_pollution_report([r1])
    dump = report.model_dump(mode="json")
    assert "total_records" in dump
    assert "stale_summary_incidents" in dump
    assert "duplicate_context_incidents" in dump
    assert "ungrounded_fact_incidents" in dump
    assert "hypothesis_as_fact_incidents" in dump
    assert "duplicate_context_rate" in dump
    assert "ungrounded_fact_rate" in dump
    assert "hypothesis_as_fact_rate" in dump
    assert "items" not in dump
    assert "omitted" not in dump
    assert "events" not in dump
    assert "tool_output" not in dump


def test_schema_version_is_pollution_metrics_v1() -> None:
    report = build_pollution_report([])
    assert report.schema_version == "pollution-metrics.v1"


def test_total_records_matches_input_length() -> None:
    records = [PollutionRecord() for _ in range(5)]
    report = build_pollution_report(records)
    assert report.total_records == 5


# ---------------------------------------------------------------------------
# End-to-end: raw deny policy through measure_context_pack -> build_pollution_report
# ---------------------------------------------------------------------------


def test_e2e_raw_deny_keeps_raw_tokens_at_zero_in_aggregate() -> None:
    """Default deny policy must keep total_raw_tool_tokens_in_prompt at 0."""
    all_records: list[PollutionRecord] = []
    for i in range(3):
        raw_items = [_raw(f"r-{i}-{j}", "stdout", "x" * 500) for j in range(3)]
        pack, _ = _pack_with(raw_items=raw_items)
        all_records.append(measure_context_pack(pack))

    report = build_pollution_report(all_records)
    assert report.total_raw_tool_tokens_in_prompt == 0
    assert report.total_records == 3


def test_e2e_full_pipeline_produces_valid_report() -> None:
    """Full pipeline: build pack, measure, aggregate into report."""
    summaries_a = [
        _summary("s-1", facts=[_fact("fact one"), _fact("fact two")]),
        _summary("s-2", facts=[_fact("fact three")], validity_status="stale"),
    ]
    summaries_b = [
        _summary("s-3", facts=[_fact("x")]),
        _summary("s-4", facts=[_fact("x")]),
    ]

    pack_a, _ = _pack_with(summaries=summaries_a)
    pack_b, _ = _pack_with(summaries=summaries_b)

    vr = _validation_result(
        "s-1",
        [
            _validation_issue("ungrounded_fact", "no evidence"),
            _validation_issue("hypothesis_as_fact", "uncertainty"),
        ],
    )

    rec_a = measure_context_pack(
        pack_a, summaries=summaries_a, validation_results=[vr], full_transcript_tokens=500
    )
    rec_b = measure_context_pack(pack_b, summaries=summaries_b, full_transcript_tokens=500)

    report = build_pollution_report([rec_a, rec_b])

    assert report.total_records == 2
    assert report.stale_summary_incidents == 1
    assert report.ungrounded_fact_rate > 0.0
    assert report.hypothesis_as_fact_rate > 0.0
    assert report.total_raw_tool_tokens_in_prompt == 0
    assert report.tokens_saved_vs_full_transcript is not None
