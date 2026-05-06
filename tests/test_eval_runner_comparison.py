"""Tests for Context Firewall condition comparison eval runner (issue #42)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from photon_action_memory.eval.comparison import (
    COMPARISON_REPORT_SCHEMA,
    EVAL_CONDITIONS,
    ComparisonRecord,
    ComparisonReport,
    ConditionSummary,
    build_comparison_report,
)
from photon_action_memory.eval.runner import run_comparison, run_comparison_fixture

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rec(
    condition: str = "no_memory",
    outcome: str | None = None,
    *,
    repeated: bool = False,
    retry: bool = False,
    dup: int = 0,
    ungrounded: int = 0,
    hypothesis: int = 0,
    summaries: int = 0,
    facts: int = 0,
) -> ComparisonRecord:
    return ComparisonRecord(
        condition=condition,
        outcome=outcome,
        repeated_exploration_occurred=repeated,
        failed_action_retry=retry,
        duplicate_context_incidents=dup,
        ungrounded_fact_incidents=ungrounded,
        hypothesis_as_fact_incidents=hypothesis,
        total_summaries_evaluated=summaries,
        total_facts_evaluated=facts,
    )


def _find(report: ComparisonReport, condition: str) -> ConditionSummary:
    for cs in report.conditions:
        if cs.condition == condition:
            return cs
    raise KeyError(condition)


# ---------------------------------------------------------------------------
# EVAL_CONDITIONS constant
# ---------------------------------------------------------------------------


def test_eval_conditions_contains_all_named_conditions() -> None:
    expected = {
        "no_memory",
        "full_transcript",
        "static_summary_memory",
        "retrieval_memory",
        "photon_summary_only",
        "photon_summary_evidence",
    }
    assert expected <= EVAL_CONDITIONS


# ---------------------------------------------------------------------------
# build_comparison_report - empty and single record
# ---------------------------------------------------------------------------


def test_empty_records_yields_zero_report() -> None:
    report = build_comparison_report([])
    assert report.total_records == 0
    assert report.conditions == []


def test_single_record_success() -> None:
    report = build_comparison_report([_rec("no_memory", "accepted")])
    assert report.total_records == 1
    cs = _find(report, "no_memory")
    assert cs.task_success_rate == 1.0
    assert cs.repeated_exploration_rate == 0.0
    assert cs.failed_action_retry_rate == 0.0


def test_single_record_non_success_outcome() -> None:
    report = build_comparison_report([_rec("no_memory", "ignored")])
    cs = _find(report, "no_memory")
    assert cs.task_success_rate == 0.0


def test_single_record_no_outcome_is_not_success() -> None:
    report = build_comparison_report([_rec("no_memory", None)])
    cs = _find(report, "no_memory")
    assert cs.task_success_rate == 0.0


# ---------------------------------------------------------------------------
# build_comparison_report - task_success_rate
# ---------------------------------------------------------------------------


def test_task_success_rate_accepted() -> None:
    records = [
        _rec("photon_summary_only", "accepted"),
        _rec("photon_summary_only", "accepted"),
        _rec("photon_summary_only", "ignored"),
    ]
    report = build_comparison_report(records)
    cs = _find(report, "photon_summary_only")
    assert cs.task_success_rate == pytest.approx(2 / 3)


def test_task_success_rate_success_outcome() -> None:
    records = [
        _rec("retrieval_memory", "success"),
        _rec("retrieval_memory", "fail"),
    ]
    report = build_comparison_report(records)
    cs = _find(report, "retrieval_memory")
    assert cs.task_success_rate == 0.5


def test_task_success_rate_completed_outcome() -> None:
    records = [_rec("full_transcript", "completed")]
    report = build_comparison_report(records)
    cs = _find(report, "full_transcript")
    assert cs.task_success_rate == 1.0


# ---------------------------------------------------------------------------
# build_comparison_report - repeated_exploration_rate
# ---------------------------------------------------------------------------


def test_repeated_exploration_rate() -> None:
    records = [
        _rec("photon_summary_evidence", repeated=True),
        _rec("photon_summary_evidence", repeated=True),
        _rec("photon_summary_evidence", repeated=False),
        _rec("photon_summary_evidence", repeated=False),
    ]
    report = build_comparison_report(records)
    cs = _find(report, "photon_summary_evidence")
    assert cs.repeated_exploration_rate == 0.5


def test_repeated_exploration_rate_zero_when_none_occurred() -> None:
    records = [_rec("no_memory"), _rec("no_memory")]
    report = build_comparison_report(records)
    cs = _find(report, "no_memory")
    assert cs.repeated_exploration_rate == 0.0


# ---------------------------------------------------------------------------
# build_comparison_report - failed_action_retry_rate
# ---------------------------------------------------------------------------


def test_failed_action_retry_rate() -> None:
    records = [
        _rec("static_summary_memory", retry=True),
        _rec("static_summary_memory", retry=False),
        _rec("static_summary_memory", retry=False),
    ]
    report = build_comparison_report(records)
    cs = _find(report, "static_summary_memory")
    assert cs.failed_action_retry_rate == pytest.approx(1 / 3)


def test_failed_action_retry_rate_all_retried() -> None:
    records = [_rec("full_transcript", retry=True) for _ in range(3)]
    report = build_comparison_report(records)
    cs = _find(report, "full_transcript")
    assert cs.failed_action_retry_rate == 1.0


# ---------------------------------------------------------------------------
# build_comparison_report - pollution rates integrated from issue #41
# ---------------------------------------------------------------------------


def test_duplicate_context_rate_by_condition() -> None:
    records = [
        _rec("photon_summary_evidence", dup=1, summaries=4),
        _rec("photon_summary_evidence", dup=1, summaries=4),
    ]
    report = build_comparison_report(records)
    cs = _find(report, "photon_summary_evidence")
    assert cs.duplicate_context_rate == pytest.approx(2 / 8)


def test_ungrounded_fact_rate_by_condition() -> None:
    records = [
        _rec("photon_summary_only", ungrounded=3, facts=10),
        _rec("photon_summary_only", ungrounded=1, facts=10),
    ]
    report = build_comparison_report(records)
    cs = _find(report, "photon_summary_only")
    assert cs.ungrounded_fact_rate == pytest.approx(4 / 20)


def test_hypothesis_as_fact_rate_by_condition() -> None:
    records = [
        _rec("retrieval_memory", hypothesis=2, facts=8),
    ]
    report = build_comparison_report(records)
    cs = _find(report, "retrieval_memory")
    assert cs.hypothesis_as_fact_rate == pytest.approx(2 / 8)


def test_pollution_rates_zero_when_no_facts_evaluated() -> None:
    records = [_rec("no_memory", ungrounded=0, hypothesis=0, facts=0)]
    report = build_comparison_report(records)
    cs = _find(report, "no_memory")
    assert cs.ungrounded_fact_rate == 0.0
    assert cs.hypothesis_as_fact_rate == 0.0


def test_pollution_rates_zero_when_no_summaries_evaluated() -> None:
    records = [_rec("no_memory", dup=0, summaries=0)]
    report = build_comparison_report(records)
    cs = _find(report, "no_memory")
    assert cs.duplicate_context_rate == 0.0


# ---------------------------------------------------------------------------
# build_comparison_report - multiple conditions grouped and sorted
# ---------------------------------------------------------------------------


def test_multiple_conditions_grouped() -> None:
    records = [
        _rec("no_memory", "accepted"),
        _rec("photon_summary_evidence", "ignored"),
        _rec("no_memory", "ignored"),
        _rec("photon_summary_evidence", "accepted"),
    ]
    report = build_comparison_report(records)
    assert report.total_records == 4
    assert len(report.conditions) == 2
    nm = _find(report, "no_memory")
    pse = _find(report, "photon_summary_evidence")
    assert nm.total_records == 2
    assert pse.total_records == 2
    assert nm.task_success_rate == 0.5
    assert pse.task_success_rate == 0.5


def test_conditions_sorted_alphabetically() -> None:
    records = [
        _rec("retrieval_memory"),
        _rec("no_memory"),
        _rec("full_transcript"),
    ]
    report = build_comparison_report(records)
    names = [cs.condition for cs in report.conditions]
    assert names == sorted(names)


def test_six_named_conditions_all_present() -> None:
    records = [_rec(c) for c in sorted(EVAL_CONDITIONS)]
    report = build_comparison_report(records)
    assert {cs.condition for cs in report.conditions} == EVAL_CONDITIONS


# ---------------------------------------------------------------------------
# build_comparison_report - dict records (fixture-style input)
# ---------------------------------------------------------------------------


def test_dict_records_parsed_correctly() -> None:
    raw = [
        {
            "condition": "photon_summary_only",
            "outcome": "accepted",
            "repeated_exploration_occurred": True,
            "failed_action_retry": False,
            "raw_log": "must be ignored by extra=ignore",
        }
    ]
    report = build_comparison_report(raw)
    cs = _find(report, "photon_summary_only")
    assert cs.task_success_rate == 1.0
    assert cs.repeated_exploration_rate == 1.0


def test_unknown_fields_ignored_via_extra_ignore() -> None:
    raw = [{"condition": "no_memory", "outcome": "success", "prompt": "secret prompt text"}]
    report = build_comparison_report(raw)
    dump = report.model_dump(mode="json")
    assert "prompt" not in dump
    assert "prompt" not in str(dump)


# ---------------------------------------------------------------------------
# build_comparison_report - report shape (aggregate-only)
# ---------------------------------------------------------------------------


def test_schema_version_is_comparison_metrics_v1() -> None:
    report = build_comparison_report([])
    assert report.schema_version == COMPARISON_REPORT_SCHEMA
    assert report.schema_version == "comparison-metrics.v1"


def test_report_is_aggregate_only() -> None:
    """Report dump must not include raw logs, prompts, or tool outputs."""
    records = [_rec("no_memory", "accepted", repeated=True, retry=False)]
    report = build_comparison_report(records)
    dump = report.model_dump(mode="json")

    assert "total_records" in dump
    assert "conditions" in dump
    assert "schema_version" in dump

    assert "raw_log" not in dump
    assert "prompt" not in dump
    assert "tool_output" not in dump
    assert "events" not in dump
    assert "suggestions" not in dump
    assert "actual_next_action" not in dump


def test_condition_summary_fields_present() -> None:
    records = [_rec("full_transcript", "accepted", repeated=True, retry=True)]
    report = build_comparison_report(records)
    cs = _find(report, "full_transcript")
    assert hasattr(cs, "task_success_rate")
    assert hasattr(cs, "repeated_exploration_rate")
    assert hasattr(cs, "failed_action_retry_rate")
    assert hasattr(cs, "duplicate_context_rate")
    assert hasattr(cs, "ungrounded_fact_rate")
    assert hasattr(cs, "hypothesis_as_fact_rate")


# ---------------------------------------------------------------------------
# run_comparison - runner integration
# ---------------------------------------------------------------------------


def test_run_comparison_returns_report() -> None:
    records = [_rec("no_memory", "success"), _rec("full_transcript", "success")]
    report = run_comparison(records)
    assert isinstance(report, ComparisonReport)
    assert report.total_records == 2


def test_run_comparison_writes_aggregate_json(tmp_path: Path) -> None:
    records = [
        _rec("photon_summary_evidence", "accepted", dup=1, summaries=4, facts=6),
        _rec("no_memory", "ignored"),
    ]
    output_path = tmp_path / "comparison.json"
    report = run_comparison(records, output_path=output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload == report.model_dump(mode="json")

    # Aggregate-only: no raw fields
    assert "raw_log" not in payload
    assert "prompt" not in payload
    assert "tool_output" not in payload
    assert "records" not in payload
    assert "total_records" in payload
    assert "conditions" in payload


def test_run_comparison_no_output_path_does_not_write(tmp_path: Path) -> None:
    records = [_rec("no_memory")]
    run_comparison(records, output_path=None)
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# run_comparison_fixture - fixture loading
# ---------------------------------------------------------------------------


def test_run_comparison_fixture_from_json_list(tmp_path: Path) -> None:
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(
        json.dumps(
            [
                {"condition": "photon_summary_only", "outcome": "accepted"},
                {"condition": "photon_summary_only", "outcome": "ignored"},
                {"condition": "no_memory", "outcome": "accepted"},
            ]
        ),
        encoding="utf-8",
    )
    report = run_comparison_fixture(fixture_path)
    assert report.total_records == 3
    cs = _find(report, "photon_summary_only")
    assert cs.task_success_rate == 0.5
    assert cs.total_records == 2


def test_run_comparison_fixture_from_records_object(tmp_path: Path) -> None:
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "condition": "retrieval_memory",
                        "outcome": "success",
                        "repeated_exploration_occurred": True,
                        "failed_action_retry": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    report = run_comparison_fixture(fixture_path)
    assert report.total_records == 1
    cs = _find(report, "retrieval_memory")
    assert cs.repeated_exploration_rate == 1.0
    assert cs.failed_action_retry_rate == 1.0


def test_run_comparison_fixture_writes_output(tmp_path: Path) -> None:
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(
        json.dumps([{"condition": "no_memory", "outcome": "accepted"}]),
        encoding="utf-8",
    )
    output_path = tmp_path / "out" / "comparison.json"
    report = run_comparison_fixture(fixture_path, output_path=output_path)
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload == report.model_dump(mode="json")


# ---------------------------------------------------------------------------
# ComparisonRecord field validation
# ---------------------------------------------------------------------------


def test_comparison_record_defaults() -> None:
    rec = ComparisonRecord()
    assert rec.condition == "no_memory"
    assert rec.outcome is None
    assert rec.repeated_exploration_occurred is False
    assert rec.failed_action_retry is False
    assert rec.duplicate_context_incidents == 0
    assert rec.ungrounded_fact_incidents == 0
    assert rec.hypothesis_as_fact_incidents == 0
    assert rec.total_summaries_evaluated == 0
    assert rec.total_facts_evaluated == 0


def test_comparison_record_negative_incidents_rejected() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ComparisonRecord(duplicate_context_incidents=-1)
