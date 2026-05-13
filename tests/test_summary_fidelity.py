"""Tests for SummaryFidelityChecker and POST /v1/summary/validate.

Acceptance criteria covered:
- missing evidence IDs are reported
- facts with evidence pass
- facts without evidence are flagged
- fact text unsupported by evidence is flagged
- hypothesis-like uncertainty in facts is flagged, while hypotheses are allowed
- failed action recorded as successful action is flagged
- score is computed and bounded
- result is aggregate/prompt-safe and does not leak raw full evidence
- API route works with request extras
- API route fail-open behavior
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionDone,
    ActionSummary,
    Fact,
    FailedAttempt,
    Hypothesis,
)
from photon_action_memory.api.server import create_app
from photon_action_memory.eval.summary_fidelity import SummaryFidelityChecker
from photon_action_memory.memory.store import SQLiteEventStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SV2 = DEFAULT_SCHEMA_VERSION_V2


def _summary(
    summary_id: str = "sum-001",
    facts: list[Fact] | None = None,
    hypotheses: list[Hypothesis] | None = None,
    failed_attempts: list[FailedAttempt] | None = None,
    actions_done: list[ActionDone] | None = None,
) -> ActionSummary:
    return ActionSummary(
        schema_version=SV2,
        summary_id=summary_id,
        facts=facts or [],
        hypotheses=hypotheses or [],
        failed_attempts=failed_attempts or [],
        actions_done=actions_done or [],
    )


def _fact(text: str, evidence_ids: list[str] | None = None) -> Fact:
    return Fact(text=text, evidence_ids=evidence_ids or [])


def _hypothesis(text: str, evidence_ids: list[str] | None = None) -> Hypothesis:
    return Hypothesis(text=text, evidence_ids=evidence_ids or [])


def _action_done(
    kind: str = "test_verification",
    command: str | None = "pytest",
    outcome: str = "success",
    status: str = "success",
    target: str | None = None,
    evidence_ids: list[str] | None = None,
) -> ActionDone:
    return ActionDone(
        kind=kind,
        command=command,
        target=target,
        outcome=outcome,
        status=status,
        evidence_ids=evidence_ids or [],
    )


def _failed_attempt(action: str = "pytest", outcome: str = "exit code 1") -> FailedAttempt:
    return FailedAttempt(action=action, outcome=outcome)


def _record(evidence_id: str, **kwargs: Any) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "kind": kwargs.pop("kind", "file_inspection"),
        "summary": kwargs.pop("summary", "test summary"),
        **kwargs,
    }


def _api_client(tmp_path: Path) -> TestClient:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    return TestClient(app)


def _validate_payload(
    summary_id: str = "sum-001",
    summaries: list[dict[str, Any]] | None = None,
    evidence_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    req: dict[str, Any] = {
        "schema_version": SV2,
        "request_id": "req-validate-001",
        "summary_ids": [summary_id],
    }
    if summaries is not None:
        req["summaries"] = summaries
    if evidence_records is not None:
        req["evidence_records"] = evidence_records
    return req


def _summary_dict(
    summary_id: str = "sum-001",
    facts: list[dict[str, Any]] | None = None,
    failed_attempts: list[dict[str, Any]] | None = None,
    actions_done: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SV2,
        "summary_id": summary_id,
        "facts": facts or [],
        "hypotheses": [],
        "failed_attempts": failed_attempts or [],
        "actions_done": actions_done or [],
    }


# ---------------------------------------------------------------------------
# SummaryFidelityChecker - missing evidence_id
# ---------------------------------------------------------------------------


def test_missing_evidence_ids_reported() -> None:
    checker = SummaryFidelityChecker()
    result = checker.check(_summary(facts=[_fact("the test passed")]))
    assert any(iss.kind == "missing_evidence_id" for iss in result.issues)
    assert result.status == "invalid"


def test_facts_without_evidence_flagged() -> None:
    checker = SummaryFidelityChecker()
    result = checker.check(_summary(facts=[_fact("the build succeeded", [])]))
    assert any(iss.kind == "missing_evidence_id" for iss in result.issues)


def test_multiple_facts_missing_evidence_all_reported() -> None:
    checker = SummaryFidelityChecker()
    result = checker.check(
        _summary(facts=[_fact("fact one"), _fact("fact two"), _fact("fact three")])
    )
    missing = [iss for iss in result.issues if iss.kind == "missing_evidence_id"]
    assert len(missing) == 3


# ---------------------------------------------------------------------------
# SummaryFidelityChecker - facts with evidence pass
# ---------------------------------------------------------------------------


def test_facts_with_evidence_pass() -> None:
    records = [_record("ev-001")]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("the test passed", ["ev-001"])]))
    blocking = [
        iss for iss in result.issues if iss.kind in ("missing_evidence_id", "ungrounded_fact")
    ]
    assert not blocking
    assert result.status == "valid"


def test_facts_with_evidence_and_no_records_not_flagged_as_ungrounded() -> None:
    checker = SummaryFidelityChecker(records=None)
    result = checker.check(_summary(facts=[_fact("fact text", ["ev-999"])]))
    assert not any(iss.kind == "ungrounded_fact" for iss in result.issues)


# ---------------------------------------------------------------------------
# SummaryFidelityChecker - ungrounded facts (unsupported by evidence)
# ---------------------------------------------------------------------------


def test_fact_text_unsupported_by_evidence_flagged() -> None:
    records = [_record("ev-001")]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("the test passed", ["ev-999"])]))
    assert any(iss.kind == "ungrounded_fact" for iss in result.issues)
    assert result.status == "invalid"


def test_fact_text_contradicts_evidence_content_flagged() -> None:
    records = [_record("ev-001", content="pytest failed with exit code 1")]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("pytest passed", ["ev-001"])]))
    assert any(iss.kind == "ungrounded_fact" for iss in result.issues)
    assert result.status == "invalid"


def test_fact_text_supported_by_evidence_content_passes() -> None:
    records = [_record("ev-001", content="pytest passed and all checks completed")]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("pytest passed", ["ev-001"])]))
    assert not any(iss.kind == "ungrounded_fact" for iss in result.issues)
    assert result.status == "valid"


def test_fact_grounding_uses_nested_payload_content() -> None:
    records = [_record("ev-001", payload={"message": "database migration completed"})]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("migration completed", ["ev-001"])]))
    assert result.status == "valid"


def test_ungrounded_fact_message_contains_evidence_id_not_full_content() -> None:
    raw_content = "SECRET_KEY=abc123 raw full evidence body here"
    records = [_record("ev-001", content=raw_content)]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("the test passed", ["ev-bad"])]))
    issue = next(iss for iss in result.issues if iss.kind == "ungrounded_fact")
    assert "ev-bad" in issue.message
    assert "SECRET_KEY" not in issue.message
    assert raw_content not in issue.message


def test_partial_evidence_ids_some_missing_flagged() -> None:
    records = [_record("ev-001"), _record("ev-002")]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("fact", ["ev-001", "ev-bad"])]))
    assert any(iss.kind == "ungrounded_fact" for iss in result.issues)


def test_all_evidence_ids_found_no_ungrounded_issue() -> None:
    records = [_record("ev-001"), _record("ev-002")]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("fact", ["ev-001", "ev-002"])]))
    assert not any(iss.kind == "ungrounded_fact" for iss in result.issues)


# ---------------------------------------------------------------------------
# SummaryFidelityChecker - hypothesis-like uncertainty in facts
# ---------------------------------------------------------------------------


def test_uncertainty_language_in_fact_flagged() -> None:
    records = [_record("ev-001")]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("the test might have passed", ["ev-001"])]))
    assert any(iss.kind == "hypothesis_as_fact" for iss in result.issues)
    assert result.status == "partial"


def test_maybe_keyword_triggers_hypothesis_as_fact() -> None:
    records = [_record("ev-001")]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("maybe the fix is ready", ["ev-001"])]))
    assert any(iss.kind == "hypothesis_as_fact" for iss in result.issues)


def test_probably_keyword_triggers_hypothesis_as_fact() -> None:
    records = [_record("ev-001")]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("the build probably succeeded", ["ev-001"])]))
    assert any(iss.kind == "hypothesis_as_fact" for iss in result.issues)


def test_uncertain_keyword_triggers_hypothesis_as_fact() -> None:
    records = [_record("ev-001")]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("the outcome is unclear", ["ev-001"])]))
    assert any(iss.kind == "hypothesis_as_fact" for iss in result.issues)


def test_hypotheses_with_uncertainty_allowed() -> None:
    checker = SummaryFidelityChecker()
    result = checker.check(_summary(hypotheses=[_hypothesis("the test might have passed")]))
    assert not any(iss.kind == "hypothesis_as_fact" for iss in result.issues)


def test_clear_language_fact_not_flagged() -> None:
    records = [_record("ev-001")]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("the test passed", ["ev-001"])]))
    assert not any(iss.kind == "hypothesis_as_fact" for iss in result.issues)


def test_hypothesis_as_fact_message_is_prompt_safe() -> None:
    raw_content = "PRIVATE_TOKEN=secret123"
    records = [_record("ev-001", content=raw_content)]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("the test might have passed", ["ev-001"])]))
    issue = next(iss for iss in result.issues if iss.kind == "hypothesis_as_fact")
    assert "PRIVATE_TOKEN" not in issue.message
    assert raw_content not in issue.message


# ---------------------------------------------------------------------------
# SummaryFidelityChecker - raw output / secret leakage in prompt-visible fields
# ---------------------------------------------------------------------------


def test_secret_in_fact_text_flags_raw_output_in_field() -> None:
    records = [_record("ev-001")]
    checker = SummaryFidelityChecker(records=records)
    leaky = _fact("API_KEY=abcdefghijklmnop secret was committed", ["ev-001"])
    result = checker.check(_summary(facts=[leaky]))
    assert any(iss.kind == "raw_output_in_field" for iss in result.issues)
    assert result.status == "invalid"


def test_home_path_in_failed_attempt_outcome_flags_raw_leakage() -> None:
    checker = SummaryFidelityChecker()
    summary = _summary(
        failed_attempts=[_failed_attempt(action="rg", outcome="no match in /Users/alice/secrets/")],
    )
    result = checker.check(summary)
    assert any(iss.kind == "raw_output_in_field" for iss in result.issues)


def test_bearer_token_in_action_command_flags_raw_leakage() -> None:
    checker = SummaryFidelityChecker()
    summary = _summary(
        actions_done=[
            _action_done(
                command="curl -H 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789'",
                outcome="success",
                status="success",
            )
        ],
    )
    result = checker.check(summary)
    assert any(iss.kind == "raw_output_in_field" for iss in result.issues)


def test_clean_fact_does_not_trigger_raw_leakage() -> None:
    records = [_record("ev-001")]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("the build succeeded", ["ev-001"])]))
    assert not any(iss.kind == "raw_output_in_field" for iss in result.issues)


# ---------------------------------------------------------------------------
# SummaryFidelityChecker - failed action misclassification
# ---------------------------------------------------------------------------


def test_failed_action_recorded_as_successful_flagged() -> None:
    checker = SummaryFidelityChecker()
    summary = _summary(
        failed_attempts=[_failed_attempt(action="pytest", outcome="exit code 1")],
        actions_done=[_action_done(command="pytest", outcome="success", status="success")],
    )
    result = checker.check(summary)
    assert any(iss.kind == "failed_action_misclassified" for iss in result.issues)
    assert result.status == "invalid"


def test_action_done_with_failed_status_not_in_failed_attempts_flagged() -> None:
    checker = SummaryFidelityChecker()
    summary = _summary(
        actions_done=[_action_done(command="npm test", outcome="failed", status="failed")],
        failed_attempts=[],
    )
    result = checker.check(summary)
    assert any(iss.kind == "failed_action_misclassified" for iss in result.issues)
    assert result.status == "invalid"


def test_action_done_with_error_status_flagged() -> None:
    checker = SummaryFidelityChecker()
    summary = _summary(
        actions_done=[_action_done(command="make build", outcome="error", status="error")],
    )
    result = checker.check(summary)
    assert any(iss.kind == "failed_action_misclassified" for iss in result.issues)


def test_action_done_with_failed_status_in_failed_attempts_not_flagged() -> None:
    checker = SummaryFidelityChecker()
    summary = _summary(
        failed_attempts=[_failed_attempt(action="pytest", outcome="exit code 1")],
        actions_done=[_action_done(command="pytest", outcome="failed", status="failed")],
    )
    result = checker.check(summary)
    assert not any(iss.kind == "failed_action_misclassified" for iss in result.issues)


def test_successful_action_not_in_failed_attempts_clean() -> None:
    checker = SummaryFidelityChecker()
    summary = _summary(
        actions_done=[_action_done(command="pytest", outcome="success", status="success")],
        failed_attempts=[],
    )
    result = checker.check(summary)
    assert not any(iss.kind == "failed_action_misclassified" for iss in result.issues)


def test_failed_action_misclassified_message_prompt_safe() -> None:
    checker = SummaryFidelityChecker()
    summary = _summary(
        failed_attempts=[_failed_attempt(action="pytest", outcome="exit code 1")],
        actions_done=[_action_done(command="pytest", outcome="success", status="success")],
    )
    result = checker.check(summary)
    issue = next(iss for iss in result.issues if iss.kind == "failed_action_misclassified")
    assert len(issue.message) < 300


# ---------------------------------------------------------------------------
# SummaryFidelityChecker - score and status
# ---------------------------------------------------------------------------


def test_score_is_one_for_valid_summary() -> None:
    records = [_record("ev-001")]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("test passed", ["ev-001"])]))
    assert result.score is not None
    assert result.score == 1.0


def test_score_bounded_between_zero_and_one() -> None:
    checker = SummaryFidelityChecker()
    facts = [_fact(f"fact {i}") for i in range(10)]
    result = checker.check(_summary(facts=facts))
    assert result.score is not None
    assert 0.0 <= result.score <= 1.0


def test_score_lower_for_invalid_summary() -> None:
    checker = SummaryFidelityChecker(records=[_record("ev-001")])
    result = checker.check(_summary(facts=[_fact("test passed", ["ev-bad"])]))
    assert result.score is not None
    assert result.score < 1.0


def test_valid_status_when_no_issues() -> None:
    records = [_record("ev-001")]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("test passed", ["ev-001"])]))
    assert result.status == "valid"


def test_partial_status_for_non_blocking_issue_only() -> None:
    records = [_record("ev-001")]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("the test might have passed", ["ev-001"])]))
    assert result.status == "partial"


def test_invalid_status_for_blocking_issue() -> None:
    checker = SummaryFidelityChecker()
    result = checker.check(_summary(facts=[_fact("no evidence fact")]))
    assert result.status == "invalid"


def test_empty_summary_is_valid_with_score_one() -> None:
    checker = SummaryFidelityChecker()
    result = checker.check(_summary())
    assert result.status == "valid"
    assert result.score == 1.0


def test_checked_at_is_set() -> None:
    checker = SummaryFidelityChecker()
    result = checker.check(_summary())
    assert result.checked_at is not None


# ---------------------------------------------------------------------------
# SummaryFidelityChecker - prompt-safety (no raw evidence in messages)
# ---------------------------------------------------------------------------


def test_result_does_not_leak_raw_evidence_content() -> None:
    raw_body = "SECRET_PASSWORD=hunter2 full raw evidence body spanning many lines"
    records = [_record("ev-001", content=raw_body)]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("test passed", ["ev-bad"])]))
    for issue in result.issues:
        assert raw_body not in issue.message
        assert "hunter2" not in issue.message


def test_issue_messages_contain_only_ids_and_counts() -> None:
    records = [_record("ev-001")]
    checker = SummaryFidelityChecker(records=records)
    result = checker.check(_summary(facts=[_fact("test passed", ["ev-bad"])]))
    issue = next(iss for iss in result.issues if iss.kind == "ungrounded_fact")
    assert "ev-bad" in issue.message
    assert "not found" in issue.message


# ---------------------------------------------------------------------------
# SummaryFidelityChecker - check_all
# ---------------------------------------------------------------------------


def test_check_all_returns_one_result_per_summary() -> None:
    checker = SummaryFidelityChecker()
    summaries = [_summary("s1"), _summary("s2"), _summary("s3")]
    results = checker.check_all(summaries)
    assert len(results) == 3
    assert {r.summary_id for r in results} == {"s1", "s2", "s3"}


def test_check_all_empty_list_returns_empty() -> None:
    checker = SummaryFidelityChecker()
    assert checker.check_all([]) == []


# ---------------------------------------------------------------------------
# API route - POST /v1/summary/validate
# ---------------------------------------------------------------------------


def test_api_validate_empty_summaries_returns_empty_results(tmp_path: Path) -> None:
    response = _api_client(tmp_path).post(
        "/v1/summary/validate",
        json=_validate_payload(summaries=[]),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["request_id"] == "req-validate-001"
    assert data["results"] == []


def test_api_validate_with_summaries_extra(tmp_path: Path) -> None:
    response = _api_client(tmp_path).post(
        "/v1/summary/validate",
        json=_validate_payload(summaries=[_summary_dict()]),
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 1
    assert data["results"][0]["summary_id"] == "sum-001"
    assert data["results"][0]["status"] == "valid"


def test_api_validate_flags_missing_evidence(tmp_path: Path) -> None:
    summaries = [_summary_dict(facts=[{"text": "test passed", "evidence_ids": []}])]
    response = _api_client(tmp_path).post(
        "/v1/summary/validate",
        json=_validate_payload(summaries=summaries),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["results"][0]["status"] == "invalid"
    assert any(iss["kind"] == "missing_evidence_id" for iss in data["results"][0]["issues"])


def test_api_validate_with_evidence_records_extra(tmp_path: Path) -> None:
    evidence_records = [{"evidence_id": "ev-001", "kind": "file_inspection", "summary": "ok"}]
    summaries = [_summary_dict(facts=[{"text": "test passed", "evidence_ids": ["ev-001"]}])]
    response = _api_client(tmp_path).post(
        "/v1/summary/validate",
        json=_validate_payload(summaries=summaries, evidence_records=evidence_records),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["results"][0]["status"] == "valid"


def test_api_validate_flags_ungrounded_fact_via_evidence_records(tmp_path: Path) -> None:
    evidence_records = [{"evidence_id": "ev-001", "kind": "file_inspection", "summary": "ok"}]
    summaries = [_summary_dict(facts=[{"text": "test passed", "evidence_ids": ["ev-bad"]}])]
    response = _api_client(tmp_path).post(
        "/v1/summary/validate",
        json=_validate_payload(summaries=summaries, evidence_records=evidence_records),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["results"][0]["status"] == "invalid"
    assert any(iss["kind"] == "ungrounded_fact" for iss in data["results"][0]["issues"])


def test_api_validate_schema_version_in_response(tmp_path: Path) -> None:
    response = _api_client(tmp_path).post(
        "/v1/summary/validate",
        json=_validate_payload(summaries=[]),
    )
    assert response.status_code == 200
    assert response.json()["schema_version"] == SV2


def test_api_validate_fail_open_on_checker_error(tmp_path: Path) -> None:
    with patch(
        "photon_action_memory.api.server.SummaryFidelityChecker.check_all",
        side_effect=RuntimeError("checker exploded"),
    ):
        response = _api_client(tmp_path).post(
            "/v1/summary/validate",
            json=_validate_payload(summaries=[_summary_dict()]),
        )
    assert response.status_code == 200
    data = response.json()
    assert data["request_id"] == "req-validate-001"
    assert data["results"] == []


def test_api_validate_multiple_summaries(tmp_path: Path) -> None:
    summaries = [_summary_dict(f"sum-{i:03d}") for i in range(3)]
    response = _api_client(tmp_path).post(
        "/v1/summary/validate",
        json=_validate_payload(summaries=summaries),
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 3
