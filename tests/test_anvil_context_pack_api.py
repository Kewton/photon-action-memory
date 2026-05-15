"""Anvil context pack API tests (Issue #70 P7).

Tests the /v1/context/pack endpoint with Anvil-specific patterns:
- Raw tool log evidence from Anvil is denied (not prompt-visible)
- Anvil-upserted summaries resolve correctly through candidate_summary_ids
- Canary context pack fixture round-trips through the schema
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionSummary,
    ContextPack,
    ContextPackRequest,
    ContextPackResponse,
)
from photon_action_memory.api.server import create_app
from photon_action_memory.memory.store import SQLiteEventStore
from photon_action_memory.memory.summary_store import SummaryStore

FIXTURES_V2 = Path(__file__).parent / "fixtures" / "v0.2"
FIXTURES_PHOTON = Path(__file__).parent / "fixtures" / "photon"
FIXTURES_SHARED = Path(__file__).parent / "fixtures" / "shared"


def _load(directory: Path, name: str) -> object:
    return json.loads((directory / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Raw Anvil tool log evidence is denied — not prompt-visible
# ---------------------------------------------------------------------------


def test_anvil_raw_evidence_all_denied(tmp_path: Path) -> None:
    raw_request = _load(FIXTURES_PHOTON, "anvil_raw_tool_log_request.json")
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    with TestClient(app) as client:
        resp = client.post("/v1/context/pack", json=raw_request)
    assert resp.status_code == 200
    data = resp.json()
    assert data["context_pack"]["items"] == []
    assert len(data["context_pack"]["omitted"]) == 3


def test_anvil_raw_evidence_deny_decisions_have_policy(tmp_path: Path) -> None:
    raw_request = _load(FIXTURES_PHOTON, "anvil_raw_tool_log_request.json")
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    with TestClient(app) as client:
        resp = client.post("/v1/context/pack", json=raw_request)
    decisions = resp.json()["admission_decisions"]
    assert len(decisions) == 3
    for dec in decisions:
        assert dec["decision"] == "deny"
        assert dec["policy"]["raw_evidence_policy"] == "raw_tool_log_default_deny"


def test_anvil_raw_evidence_denied_item_ids_match_request(tmp_path: Path) -> None:
    raw_request = _load(FIXTURES_PHOTON, "anvil_raw_tool_log_request.json")
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    with TestClient(app) as client:
        resp = client.post("/v1/context/pack", json=raw_request)
    omitted_ids = {o["id"] for o in resp.json()["context_pack"]["omitted"]}
    assert omitted_ids == {"anvil-stdout-001", "anvil-stderr-001", "anvil-build-001"}


# ---------------------------------------------------------------------------
# Anvil summary upsert → candidate_summary_ids → context pack resolves
# ---------------------------------------------------------------------------


def test_anvil_summary_appears_in_context_pack_items(tmp_path: Path) -> None:
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    event_store = SQLiteEventStore(tmp_path / "events.sqlite")
    raw_summary = _load(FIXTURES_PHOTON, "anvil_action_summary.json")
    summary = ActionSummary.model_validate(raw_summary)
    summary_store.upsert(summary)

    body: dict[str, object] = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "pack-anvil-sum-001",
        "agent": {"name": "anvil", "version": "1.0.0"},
        "repo": {"root": "/workspace/my-repo", "name": "my-repo"},
        "task": {
            "user_request": "fix build",
            "mode": "act",
            "summary": "fixing build failure",
        },
        "working_memory": {"touched_files": []},
        "recent_event_ids": [],
        "candidate_summary_ids": ["anvil-sum-photon-001"],
        "budget": {"max_memory_tokens": 800, "max_evidence_chars": 1200},
    }
    with TestClient(create_app(event_store, summary_store)) as client:
        resp = client.post("/v1/context/pack", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["sidecar_status"] == "ok"
    assert len(data["context_pack"]["items"]) >= 1


def test_anvil_unknown_candidate_summary_id_is_skipped(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    body: dict[str, object] = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "pack-anvil-unknown-001",
        "agent": {"name": "anvil", "version": "1.0.0"},
        "repo": {"root": "/workspace/my-repo", "name": "my-repo"},
        "task": {
            "user_request": "fix something",
            "mode": "act",
            "summary": "fixing",
        },
        "working_memory": {"touched_files": []},
        "recent_event_ids": [],
        "candidate_summary_ids": ["nonexistent-anvil-sum-999"],
        "budget": {"max_memory_tokens": 800, "max_evidence_chars": 1200},
    }
    with TestClient(app) as client:
        resp = client.post("/v1/context/pack", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["sidecar_status"] == "ok"
    assert data["context_pack"]["items"] == []


def test_anvil_stale_summary_not_in_context_pack(tmp_path: Path) -> None:
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    event_store = SQLiteEventStore(tmp_path / "events.sqlite")
    raw_summary = _load(FIXTURES_PHOTON, "anvil_action_summary.json")
    summary = ActionSummary.model_validate(raw_summary)
    # Mark stale before upsert
    from photon_action_memory.api.schema_v2 import Validity

    summary = summary.model_copy(update={"validity": Validity(status="stale", reason="outdated")})
    summary_store.upsert(summary)

    body: dict[str, object] = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "pack-anvil-stale-001",
        "agent": {"name": "anvil", "version": "1.0.0"},
        "repo": {"root": "/workspace/my-repo", "name": "my-repo"},
        "task": {
            "user_request": "fix build",
            "mode": "act",
            "summary": "fixing",
        },
        "working_memory": {"touched_files": []},
        "recent_event_ids": [],
        "candidate_summary_ids": ["anvil-sum-photon-001"],
        "budget": {"max_memory_tokens": 800, "max_evidence_chars": 1200},
    }
    with TestClient(create_app(event_store, summary_store)) as client:
        resp = client.post("/v1/context/pack", json=body)
    assert resp.status_code == 200
    assert resp.json()["context_pack"]["items"] == []


# ---------------------------------------------------------------------------
# Canary context pack fixture round-trips
# ---------------------------------------------------------------------------


def test_canary_context_pack_fixture_validates_as_context_pack() -> None:
    raw = _load(FIXTURES_V2, "canary_context_pack.json")
    pack = ContextPack.model_validate(raw)
    assert pack.schema_version == DEFAULT_SCHEMA_VERSION_V2
    assert pack.mode == "summary_only"
    assert len(pack.items) > 0
    assert len(pack.omitted) > 0
    assert pack.token_budget.estimated_tokens >= 0


def test_canary_context_pack_raw_items_all_in_omitted() -> None:
    raw = _load(FIXTURES_V2, "canary_context_pack.json")
    pack = ContextPack.model_validate(raw)
    item_ids = {item.id for item in pack.items}
    omitted_ids = {o.id for o in pack.omitted}
    # raw-stdout-1 must be in omitted, not items
    assert "raw-stdout-1" in omitted_ids
    assert "raw-stdout-1" not in item_ids


def test_context_pack_omits_raw_fixture_validates() -> None:
    raw = _load(FIXTURES_V2, "context_pack_omits_raw.json")
    pack = ContextPack.model_validate(raw)
    omitted_kinds = {o.kind for o in pack.omitted}
    assert "raw_tool_output" in omitted_kinds


# ---------------------------------------------------------------------------
# Live injection fixtures — repo/task auto retrieval
# ---------------------------------------------------------------------------


def test_anvil_live_shared_fixtures_validate() -> None:
    summary = ActionSummary.model_validate(_load(FIXTURES_SHARED, "anvil_live_action_summary.json"))
    request = ContextPackRequest.model_validate(
        _load(FIXTURES_SHARED, "anvil_live_context_pack_request.json")
    )
    response = ContextPackResponse.model_validate(
        _load(FIXTURES_SHARED, "anvil_live_context_pack_response.json")
    )
    assert summary.repo_id == "anvil-live-fixture"
    assert summary.task_signature == "codename-question"
    assert request.candidate_summary_ids == []
    assert response.context_pack.items[0].kind == "action_summary"


def test_anvil_live_context_pack_auto_resolves_seed_summary(tmp_path: Path) -> None:
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    event_store = SQLiteEventStore(tmp_path / "events.sqlite")
    summary = ActionSummary.model_validate(_load(FIXTURES_SHARED, "anvil_live_action_summary.json"))
    body = _load(FIXTURES_SHARED, "anvil_live_context_pack_request.json")
    summary_store.upsert(summary)

    with TestClient(create_app(event_store, summary_store)) as client:
        resp = client.post("/v1/context/pack", json=body)

    assert resp.status_code == 200
    data = resp.json()
    assert data["sidecar_status"] == "ok"
    assert data["context_pack"]["repo_id"] == "anvil-live-fixture"
    assert data["context_pack"]["items"][0]["id"] == "anvil-live-codename-001"
    assert "heliograph" in data["context_pack"]["items"][0]["text"]
    assert data["admission_decisions"][0]["decision"] == "admit"
