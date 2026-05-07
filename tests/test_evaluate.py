"""Tests for POST /v1/evaluate ContextPack adoption logging and integration contract.

Acceptance criteria covered:
- POST /v1/evaluate with adopted ContextPack logs the event and returns logged=1
- POST /v1/evaluate with ignored ContextPack logs the event and returns ignored_reason
- POST /v1/evaluate with no context_pack_event returns logged=0
- Evaluate endpoint logs the event to the SQLite store
- EvaluateRequest and EvaluateResponse schema round-trip correctly
- Fixture JSON validates against the schema
- aggregate_context_pack_eval() computes correct adoption and outcome rates
- validate_call_sequence() correctly identifies contract violations
- IntegrationContract invariants are present and non-empty
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    EvaluateRequest,
    EvaluateResponse,
)
from photon_action_memory.api.server import create_app
from photon_action_memory.eval.context_pack_log import (
    ContextPackAdoptionReport,
    ContextPackEvalRecord,
    aggregate_context_pack_eval,
)
from photon_action_memory.integration.context_pack_contract import (
    CONTEXT_PACK_CONTRACT,
    OPTIONAL_STEPS,
    REQUIRED_STEPS,
    validate_call_sequence,
)
from photon_action_memory.memory.store import SQLiteEventStore

FIXTURES_V2 = Path(__file__).parent / "fixtures" / "v0.2"


# ---------------------------------------------------------------------------
# POST /v1/evaluate — HTTP endpoint tests
# ---------------------------------------------------------------------------


def _make_client(tmp_path: Path) -> tuple[TestClient, SQLiteEventStore]:
    store = SQLiteEventStore(tmp_path / "events.sqlite")
    return TestClient(create_app(store)), store


def test_evaluate_adopted_context_pack_returns_logged_one(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    body = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "eval-req-001",
        "session_id": "sess-1",
        "context_pack_event": {
            "context_pack_request_id": "pack-req-001",
            "adoption_status": "adopted",
            "items_adopted_count": 2,
            "items_ignored_count": 0,
            "outcome": "success",
            "latency_ms": 120.0,
        },
    }
    response = client.post("/v1/evaluate", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["logged"] == 1
    assert data["status"] == "ok"
    assert data["request_id"] == "eval-req-001"


def test_evaluate_ignored_context_pack_returns_logged_one(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    body = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "eval-req-002",
        "context_pack_event": {
            "context_pack_request_id": "pack-req-002",
            "adoption_status": "ignored",
            "ignored_reason": "existing_plan_had_higher_priority",
            "items_adopted_count": 0,
            "items_ignored_count": 3,
            "outcome": "partial",
            "latency_ms": 90.0,
        },
    }
    response = client.post("/v1/evaluate", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["logged"] == 1
    assert data["status"] == "ok"


def test_evaluate_no_context_pack_event_returns_logged_zero(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    body = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "eval-req-003",
    }
    response = client.post("/v1/evaluate", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["logged"] == 0
    assert data["status"] == "ok"


def test_evaluate_logs_event_to_store(tmp_path: Path) -> None:
    client, store = _make_client(tmp_path)
    body = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "eval-req-004",
        "context_pack_event": {
            "context_pack_request_id": "pack-req-004",
            "adoption_status": "adopted",
            "evidence_expand_requested": True,
            "evidence_ids_expanded": ["ev-ref-007"],
            "items_adopted_count": 1,
            "items_ignored_count": 0,
            "outcome": "success",
        },
    }
    response = client.post("/v1/evaluate", json=body)
    assert response.status_code == 200
    assert store.count() == 1
    stored = store.list_events()[0]
    assert stored.payload["event_type"] == "context_pack_eval"
    assert stored.payload["adoption_status"] == "adopted"
    assert stored.payload["evidence_expand_requested"] is True
    assert stored.payload["evidence_ids_expanded"] == ["ev-ref-007"]


def test_evaluate_with_evidence_expand_fields(tmp_path: Path) -> None:
    client, store = _make_client(tmp_path)
    body = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "eval-req-005",
        "context_pack_event": {
            "context_pack_request_id": "pack-req-005",
            "adoption_status": "adopted",
            "evidence_expand_requested": True,
            "evidence_ids_expanded": ["ev-ref-a", "ev-ref-b"],
            "items_adopted_count": 3,
            "items_ignored_count": 0,
            "outcome": "success",
            "latency_ms": 195.0,
        },
    }
    response = client.post("/v1/evaluate", json=body)
    assert response.status_code == 200
    assert response.json()["logged"] == 1
    stored = store.list_events()[0]
    assert stored.payload["evidence_ids_expanded"] == ["ev-ref-a", "ev-ref-b"]


# ---------------------------------------------------------------------------
# Schema round-trip
# ---------------------------------------------------------------------------


def test_evaluate_request_schema_round_trip() -> None:
    raw = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "rt-req-001",
        "session_id": "sess-rt-1",
        "context_pack_event": {
            "context_pack_request_id": "pack-rt-001",
            "adoption_status": "partial",
            "items_adopted_count": 1,
            "items_ignored_count": 2,
            "outcome": "success",
        },
    }
    req = EvaluateRequest.model_validate(raw)
    assert req.request_id == "rt-req-001"
    assert req.context_pack_event is not None
    assert req.context_pack_event.adoption_status == "partial"
    dumped = req.model_dump(mode="json")
    req2 = EvaluateRequest.model_validate(dumped)
    assert req2.context_pack_event is not None
    assert req2.context_pack_event.items_ignored_count == 2


def test_evaluate_response_schema_round_trip() -> None:
    resp = EvaluateResponse(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        request_id="rt-resp-001",
        logged=1,
        status="ok",
    )
    dumped = resp.model_dump(mode="json")
    resp2 = EvaluateResponse.model_validate(dumped)
    assert resp2.logged == 1
    assert resp2.status == "ok"


# ---------------------------------------------------------------------------
# Fixture validation
# ---------------------------------------------------------------------------


def test_evaluate_adopted_fixture_validates() -> None:
    raw = json.loads((FIXTURES_V2 / "evaluate_context_pack_adopted.json").read_text())
    req = EvaluateRequest.model_validate(raw)
    assert req.context_pack_event is not None
    assert req.context_pack_event.adoption_status == "adopted"
    assert req.context_pack_event.outcome == "success"


def test_evaluate_ignored_fixture_validates() -> None:
    raw = json.loads((FIXTURES_V2 / "evaluate_context_pack_ignored.json").read_text())
    req = EvaluateRequest.model_validate(raw)
    assert req.context_pack_event is not None
    assert req.context_pack_event.adoption_status == "ignored"
    assert req.context_pack_event.ignored_reason == "existing_plan_had_higher_priority"


def test_adoption_log_fixture_records_validate() -> None:
    raw = json.loads((FIXTURES_V2 / "context_pack_adoption_log.json").read_text())
    records = [ContextPackEvalRecord.model_validate(r) for r in raw["records"]]
    assert len(records) == 5
    statuses = {r.adoption_status for r in records}
    assert "adopted" in statuses
    assert "ignored" in statuses
    assert "partial" in statuses


# ---------------------------------------------------------------------------
# aggregate_context_pack_eval
# ---------------------------------------------------------------------------


def test_aggregate_empty_records_returns_zero_report() -> None:
    report = aggregate_context_pack_eval([])
    assert report.total_turns == 0
    assert report.adoption_rate == 0.0
    assert report.task_success_rate == 0.0


def test_aggregate_all_adopted() -> None:
    records = [
        ContextPackEvalRecord(
            context_pack_request_id=f"p-{i}",
            adoption_status="adopted",
            outcome="success",
        )
        for i in range(4)
    ]
    report = aggregate_context_pack_eval(records)
    assert report.total_turns == 4
    assert report.adopted_count == 4
    assert report.ignored_count == 0
    assert report.adoption_rate == 1.0
    assert report.task_success_rate == 1.0


def test_aggregate_mixed_adoption_and_outcomes() -> None:
    raw_records: list[dict[str, Any]] = [
        {
            "context_pack_request_id": "p-1",
            "adoption_status": "adopted",
            "outcome": "success",
            "latency_ms": 100.0,
        },
        {
            "context_pack_request_id": "p-2",
            "adoption_status": "ignored",
            "ignored_reason": "existing_plan_had_higher_priority",
            "outcome": "partial",
        },
        {
            "context_pack_request_id": "p-3",
            "adoption_status": "adopted",
            "evidence_expand_requested": True,
            "outcome": "success",
        },
        {
            "context_pack_request_id": "p-4",
            "adoption_status": "partial",
            "outcome": "success",
        },
        {
            "context_pack_request_id": "p-5",
            "adoption_status": "ignored",
            "ignored_reason": "context_pack_empty",
            "outcome": "failure",
        },
    ]
    report = aggregate_context_pack_eval(raw_records)
    assert report.total_turns == 5
    assert report.adopted_count == 2
    assert report.ignored_count == 2
    assert report.partial_count == 1
    assert report.adoption_rate == pytest.approx(3 / 5)
    assert report.evidence_expand_rate == pytest.approx(1 / 5)
    assert report.task_success_rate == pytest.approx(3 / 5)
    assert report.ignored_reason_counts == {
        "context_pack_empty": 1,
        "existing_plan_had_higher_priority": 1,
    }


def test_aggregate_from_fixture_file() -> None:
    raw = json.loads((FIXTURES_V2 / "context_pack_adoption_log.json").read_text())
    report = aggregate_context_pack_eval(raw["records"])
    assert isinstance(report, ContextPackAdoptionReport)
    assert report.total_turns == 5
    assert report.adopted_count == 2
    assert report.ignored_count == 2
    assert report.partial_count == 1
    assert report.evidence_expand_rate == pytest.approx(1 / 5)


# ---------------------------------------------------------------------------
# Integration contract — validate_call_sequence
# ---------------------------------------------------------------------------


def test_valid_complete_sequence() -> None:
    violations = validate_call_sequence(["context_pack", "evaluate"])
    assert violations == []


def test_valid_sequence_with_evidence_expand() -> None:
    violations = validate_call_sequence(["context_pack", "evidence_expand", "evaluate"])
    assert violations == []


def test_missing_context_pack_step_is_violation() -> None:
    violations = validate_call_sequence(["evaluate"])
    assert any("context_pack" in v for v in violations)


def test_missing_evaluate_step_is_violation() -> None:
    violations = validate_call_sequence(["context_pack"])
    assert any("evaluate" in v for v in violations)


def test_wrong_order_is_violation() -> None:
    violations = validate_call_sequence(["evaluate", "context_pack"])
    assert any("before" in v for v in violations)


def test_evidence_expand_without_context_pack_is_violation() -> None:
    violations = validate_call_sequence(["evidence_expand", "evaluate"])
    assert any("evidence_expand" in v for v in violations)


def test_empty_sequence_has_violations() -> None:
    violations = validate_call_sequence([])
    assert len(violations) >= 2


# ---------------------------------------------------------------------------
# Integration contract — contract structure
# ---------------------------------------------------------------------------


def test_contract_has_all_required_steps() -> None:
    step_kinds = {step.kind for step in CONTEXT_PACK_CONTRACT.steps}
    assert REQUIRED_STEPS <= step_kinds


def test_contract_has_optional_steps() -> None:
    step_kinds = {step.kind for step in CONTEXT_PACK_CONTRACT.steps}
    assert OPTIONAL_STEPS <= step_kinds


def test_contract_invariants_are_non_empty() -> None:
    assert len(CONTEXT_PACK_CONTRACT.invariants) >= 4


def test_required_steps_are_marked_required() -> None:
    for step in CONTEXT_PACK_CONTRACT.steps:
        if step.kind in REQUIRED_STEPS:
            assert step.required is True
        elif step.kind in OPTIONAL_STEPS:
            assert step.required is False


def test_contract_steps_have_endpoints() -> None:
    for step in CONTEXT_PACK_CONTRACT.steps:
        assert step.endpoint.startswith("POST /v1/")
        assert len(step.when) > 0


# ---------------------------------------------------------------------------
# Issue #67: Anvil /v1/evaluate — shadow/canary adoption_status support
# ---------------------------------------------------------------------------


def test_evaluate_request_validates_shadow_not_injected() -> None:
    raw = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "anvil-shadow-req-001",
        "context_pack_event": {
            "context_pack_request_id": "pack-shadow-001",
            "adoption_status": "shadow_not_injected",
            "ignored_reason": "shadow_mode_no_injection",
            "items_adopted_count": 0,
            "items_ignored_count": 0,
        },
    }
    req = EvaluateRequest.model_validate(raw)
    assert req.context_pack_event is not None
    assert req.context_pack_event.adoption_status == "shadow_not_injected"


def test_evaluate_request_validates_not_available() -> None:
    raw = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "anvil-shadow-req-002",
        "context_pack_event": {
            "context_pack_request_id": "pack-shadow-002",
            "adoption_status": "not_available",
            "ignored_reason": "sidecar_timeout",
            "items_adopted_count": 0,
            "items_ignored_count": 0,
        },
    }
    req = EvaluateRequest.model_validate(raw)
    assert req.context_pack_event is not None
    assert req.context_pack_event.adoption_status == "not_available"


def test_evaluate_request_validates_error_status() -> None:
    raw = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "anvil-shadow-req-003",
        "context_pack_event": {
            "context_pack_request_id": "pack-shadow-003",
            "adoption_status": "error",
            "ignored_reason": "sidecar_error",
            "items_adopted_count": 0,
            "items_ignored_count": 0,
        },
    }
    req = EvaluateRequest.model_validate(raw)
    assert req.context_pack_event is not None
    assert req.context_pack_event.adoption_status == "error"


def test_anvil_shadow_fixture_returns_logged_one(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    raw = json.loads((FIXTURES_V2 / "evaluate_anvil_shadow.json").read_text())
    response = client.post("/v1/evaluate", json=raw)
    assert response.status_code == 200
    data = response.json()
    assert data["logged"] == 1
    assert data["status"] == "ok"


def test_evaluate_payload_excludes_raw_stdout_stderr(tmp_path: Path) -> None:
    client, store = _make_client(tmp_path)
    body = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "eval-raw-out-001",
        "context_pack_event": {
            "context_pack_request_id": "pack-raw-001",
            "adoption_status": "adopted",
            "items_adopted_count": 1,
            "items_ignored_count": 0,
            "outcome": "success",
            "raw_stdout": "lots of tool output...",
            "raw_stderr": "build warnings...",
        },
    }
    response = client.post("/v1/evaluate", json=body)
    assert response.status_code == 200
    assert response.json()["logged"] == 1
    stored = store.list_events()[0]
    assert "raw_stdout" not in stored.payload
    assert "raw_stderr" not in stored.payload


def test_aggregate_counts_shadow_not_injected_not_available_error() -> None:
    raw = json.loads(
        (FIXTURES_V2 / "context_pack_adoption_log_anvil.json").read_text()
    )
    report = aggregate_context_pack_eval(raw["records"])
    assert report.total_turns == 5
    assert report.adopted_count == 2
    assert report.shadow_not_injected_count == 1
    assert report.not_available_count == 1
    assert report.error_count == 1


def test_evaluate_malformed_empty_request_id_returns_degraded(tmp_path: Path) -> None:
    client, store = _make_client(tmp_path)
    body = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "eval-malformed-001",
        "context_pack_event": {
            "context_pack_request_id": "",
            "adoption_status": "adopted",
            "items_adopted_count": 1,
            "items_ignored_count": 0,
        },
    }
    response = client.post("/v1/evaluate", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["logged"] == 1
    assert data["status"] == "degraded"
    assert any(w["kind"] == "malformed_eval_input" for w in data["warnings"])
