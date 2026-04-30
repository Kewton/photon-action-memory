from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from photon_action_memory import SCHEMA_VERSION
from photon_action_memory.api.schema import (
    EvaluationRequest,
    EventRequest,
    SidecarEvent,
    SuggestRequest,
    SuggestResponse,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "anvil_shadow_mode"


def test_minimal_suggest_request_round_trip() -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "request_id": "turn-001",
        "agent": {"name": "anvil"},
        "repo": {"root": "/repo"},
        "task": {"user_request": "Fix the failing test", "mode": "act"},
        "working_memory": {},
    }

    request = SuggestRequest.model_validate(payload)
    round_tripped = SuggestRequest.model_validate_json(request.model_dump_json())

    assert round_tripped.schema_version == SCHEMA_VERSION
    assert round_tripped.request_id == "turn-001"
    assert round_tripped.agent.name == "anvil"
    assert round_tripped.budget.max_suggestions == 8
    assert round_tripped.recent_events == []


def test_unknown_optional_fields_are_preserved() -> None:
    request = SuggestRequest.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "request_id": "turn-unknown-extra",
            "agent": {"name": "anvil", "build_channel": "nightly"},
            "repo": {"root": "/repo"},
            "task": {"user_request": "Inspect state", "mode": "plan"},
            "working_memory": {"active_task": "inspect state", "custom_slot": {"value": 1}},
            "shadow_mode": True,
        }
    )

    dumped = request.model_dump()

    assert dumped["shadow_mode"] is True
    assert dumped["agent"]["build_channel"] == "nightly"
    assert dumped["working_memory"]["custom_slot"] == {"value": 1}


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            SuggestRequest,
            {
                "request_id": "missing-version",
                "agent": {"name": "anvil"},
                "repo": {"root": "/repo"},
                "task": {"user_request": "Fix", "mode": "act"},
                "working_memory": {},
            },
        ),
        (
            SuggestResponse,
            {
                "request_id": "missing-version",
                "model_version": "photon-action-memory-v0.1.0",
            },
        ),
        (
            SidecarEvent,
            {
                "event_id": "evt-001",
                "session_id": "sess-001",
                "timestamp": "2026-04-30T12:00:00Z",
                "event_type": "tool_result",
                "summary": "grep succeeded",
            },
        ),
    ],
)
def test_schema_version_is_required(model: type[object], payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)  # type: ignore[attr-defined]


def test_required_field_missing_is_validation_error() -> None:
    with pytest.raises(ValidationError) as exc_info:
        SuggestRequest.model_validate(
            {
                "schema_version": SCHEMA_VERSION,
                "request_id": "turn-002",
                "agent": {"name": "anvil"},
                "repo": {"root": "/repo"},
                "working_memory": {},
            }
        )

    assert "task" in str(exc_info.value)


def test_malformed_schema_version_is_validation_error() -> None:
    with pytest.raises(ValidationError):
        SuggestResponse.model_validate(
            {
                "schema_version": "action-memory.v2",
                "request_id": "turn-003",
                "model_version": "photon-action-memory-v0.1.0",
            }
        )


def test_anvil_working_memory_fixture_round_trip() -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "request_id": "anvil-turn-42",
        "agent": {"name": "anvil", "version": "0.1.x"},
        "repo": {
            "root": "/Users/example/work/Anvil",
            "name": "Anvil",
            "branch": "feature/example",
            "commit": "HEAD",
        },
        "task": {
            "user_request": "Define a schema for sidecar messages",
            "mode": "act",
            "summary": "Implement v1 schema models",
        },
        "working_memory": {
            "active_task": "Implement schema-first DTOs",
            "constraints": ["Do not store raw secrets", "Keep sidecar fail-open"],
            "touched_files": ["photon_action_memory/api/schema.py", "tests/test_schema.py"],
            "unresolved_errors": ["mypy has not run yet"],
            "active_precautions": ["Preserve unknown optional fields"],
            "plan": ["Read docs", "Implement models", "Add tests"],
            "completed_steps": ["Read docs"],
            "pending_steps": ["Run focused verification"],
            "evidence_ids": ["evt-001"],
            "anvil_working_memory": {
                "mode": "act",
                "active_files": ["src/session/store.rs"],
                "tool_loop": {"last_tool": "rg", "last_status": "success"},
            },
        },
        "recent_events": [
            {
                "type": "tool_result",
                "tool": "rg",
                "status": "success",
                "summary": "found WorkingMemory integration points",
                "event_id": "evt-001",
            }
        ],
        "budget": {"max_suggestions": 3, "max_evidence_chars": 1200},
    }

    request = SuggestRequest.model_validate(payload)
    round_tripped = SuggestRequest.model_validate_json(request.model_dump_json())

    assert round_tripped.working_memory.active_task == "Implement schema-first DTOs"
    assert round_tripped.working_memory.touched_files == [
        "photon_action_memory/api/schema.py",
        "tests/test_schema.py",
    ]
    assert round_tripped.model_dump()["working_memory"]["anvil_working_memory"]["mode"] == "act"
    assert round_tripped.recent_events[0].type == "tool_result"


def test_anvil_shadow_mode_contract_fixtures_validate() -> None:
    request = SuggestRequest.model_validate_json(
        (FIXTURE_ROOT / "suggest_request.json").read_text()
    )
    response = SuggestResponse.model_validate_json(
        (FIXTURE_ROOT / "suggest_response.json").read_text()
    )
    event = EventRequest.model_validate_json((FIXTURE_ROOT / "event_request.json").read_text())
    evaluation = EvaluationRequest.model_validate_json(
        (FIXTURE_ROOT / "evaluate_request.json").read_text()
    )

    response_suggestion_ids = [item.id for item in response.suggestions if item.id]
    adopted_record, ignored_record = evaluation.records
    event_metadata = event.events[0].artifacts[0].metadata

    assert request.request_id == "anvil-shadow-req-0001"
    assert request.model_dump()["shadow_mode"] is True
    assert response.request_id == request.request_id
    assert response_suggestion_ids == [
        "sug-read-turn-loop",
        "sug-read-session-store",
        "sug-search-shadow-eval",
    ]
    assert adopted_record.request_id == request.request_id
    assert adopted_record.suggestion_ids == response_suggestion_ids
    assert adopted_record.actual_next_action.kind == "read"
    assert adopted_record.actual_next_action.target == "src/agent/loop_run/turn.rs"
    assert adopted_record.matched is True
    assert adopted_record.ignored_reason is None
    assert adopted_record.outcome == "success"
    assert adopted_record.latency_ms == 184.2
    assert adopted_record.sidecar_status == "ok"
    assert event.events[0].event_type == "shadow_evaluation"
    assert event_metadata["suggestion_ids"] == response_suggestion_ids
    assert event_metadata["matched"] is True
    assert event_metadata["sidecar_status"] == "ok"
    assert ignored_record.matched is False
    assert ignored_record.ignored_reason == "existing_plan_had_higher_priority"
    assert ignored_record.outcome == "partial"


def test_event_payload_round_trip_accepts_type_alias() -> None:
    event = SidecarEvent.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "event_id": "evt-001",
            "session_id": "sess-001",
            "turn_id": "turn-001",
            "repo_id": "repo-anvil",
            "timestamp": "2026-04-30T12:00:00Z",
            "type": "tool_result",
            "tool_name": "pytest",
            "status": "success",
            "summary": "schema tests passed",
            "artifacts": [{"kind": "command", "value": "pytest tests/test_schema.py"}],
            "redaction_status": "sanitized",
        }
    )

    round_tripped = SidecarEvent.model_validate_json(event.model_dump_json())

    assert round_tripped.schema_version == SCHEMA_VERSION
    assert round_tripped.event_type == "tool_result"
    assert round_tripped.artifacts[0].value == "pytest tests/test_schema.py"
