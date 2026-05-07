"""Shared JSON fixture tests for Anvil / photon-action-memory schema-drift detection (Issue #71).

Both repos must be able to parse every fixture in tests/fixtures/shared/.
When the shared fixtures change in either repo, the other side should fail
these tests — that is the schema-drift signal.

Fixture inventory:
- evaluate_shadow_not_injected.json   EvaluateRequest with adoption_status=shadow_not_injected
- context_pack_request_with_raw_log.json  ContextPackRequest carrying raw stdout/stderr evidence
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ContextPackRequest,
    EvaluateRequest,
)
from photon_action_memory.api.server import create_app
from photon_action_memory.memory.store import SQLiteEventStore

SHARED = Path(__file__).parent / "fixtures" / "shared"


def _load(name: str) -> object:
    return json.loads((SHARED / name).read_text(encoding="utf-8"))


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(SQLiteEventStore(tmp_path / "events.sqlite")))


# ---------------------------------------------------------------------------
# evaluate_shadow_not_injected.json — parseable by both repos
# ---------------------------------------------------------------------------


def test_shared_shadow_not_injected_parses_as_evaluate_request() -> None:
    raw = _load("evaluate_shadow_not_injected.json")
    req = EvaluateRequest.model_validate(raw)
    assert req.schema_version == DEFAULT_SCHEMA_VERSION_V2
    assert req.agent is not None
    assert req.agent.name == "anvil"
    assert req.context_pack_event is not None
    assert req.context_pack_event.adoption_status == "shadow_not_injected"
    assert req.context_pack_event.ignored_reason == "shadow_mode_no_injection"
    assert req.context_pack_event.items_adopted_count == 0


def test_shared_shadow_not_injected_round_trips() -> None:
    raw = _load("evaluate_shadow_not_injected.json")
    req = EvaluateRequest.model_validate(raw)
    rt = EvaluateRequest.model_validate_json(req.model_dump_json())
    assert rt.context_pack_event is not None
    assert rt.context_pack_event.adoption_status == "shadow_not_injected"
    assert rt.context_pack_event.latency_ms == pytest.approx(42.0)


def test_shared_shadow_not_injected_stores_via_api(tmp_path: Path) -> None:
    raw = _load("evaluate_shadow_not_injected.json")
    with _client(tmp_path) as client:
        resp = client.post("/v1/evaluate", json=raw)
    assert resp.status_code == 200
    data = resp.json()
    assert data["logged"] == 1
    assert data["status"] == "ok"


def test_shared_shadow_not_injected_payload_stored_correctly(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite")
    with TestClient(create_app(store)) as client:
        raw = _load("evaluate_shadow_not_injected.json")
        client.post("/v1/evaluate", json=raw)
    assert store.count() == 1
    stored = store.list_events()[0]
    assert stored.payload["adoption_status"] == "shadow_not_injected"
    assert stored.payload["ignored_reason"] == "shadow_mode_no_injection"


# ---------------------------------------------------------------------------
# context_pack_request_with_raw_log.json — unsafe raw log not in items
# ---------------------------------------------------------------------------


def test_shared_raw_log_parses_as_context_pack_request() -> None:
    raw = _load("context_pack_request_with_raw_log.json")
    req = ContextPackRequest.model_validate(raw)
    assert req.schema_version == DEFAULT_SCHEMA_VERSION_V2
    assert req.agent is not None
    assert req.agent.name == "anvil"


def test_shared_raw_log_round_trips() -> None:
    raw = _load("context_pack_request_with_raw_log.json")
    req = ContextPackRequest.model_validate(raw)
    rt = ContextPackRequest.model_validate_json(req.model_dump_json())
    assert rt.request_id == "shared-pack-raw-001"


def test_shared_raw_log_not_in_context_pack_items(tmp_path: Path) -> None:
    raw = _load("context_pack_request_with_raw_log.json")
    with _client(tmp_path) as client:
        resp = client.post("/v1/context/pack", json=raw)
    assert resp.status_code == 200
    data = resp.json()
    pack = data["context_pack"]
    assert pack["items"] == [], "raw log evidence must not appear in ContextPack items"
    omitted_ids = {o["id"] for o in pack["omitted"]}
    assert "shared-stdout-001" in omitted_ids
    assert "shared-stderr-001" in omitted_ids


def test_shared_raw_log_omitted_with_deny_decision(tmp_path: Path) -> None:
    raw = _load("context_pack_request_with_raw_log.json")
    with _client(tmp_path) as client:
        resp = client.post("/v1/context/pack", json=raw)
    assert resp.status_code == 200
    data = resp.json()
    decisions = data.get("admission_decisions", [])
    deny_decisions = [d for d in decisions if d["decision"] == "deny"]
    assert len(deny_decisions) >= 2


# ---------------------------------------------------------------------------
# Cross-fixture: fixture file completeness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "evaluate_shadow_not_injected.json",
        "context_pack_request_with_raw_log.json",
    ],
)
def test_shared_fixture_is_valid_json(filename: str) -> None:
    content = (SHARED / filename).read_text(encoding="utf-8")
    parsed = json.loads(content)
    assert isinstance(parsed, dict)
    assert "schema_version" in parsed
    assert parsed["schema_version"] == DEFAULT_SCHEMA_VERSION_V2
