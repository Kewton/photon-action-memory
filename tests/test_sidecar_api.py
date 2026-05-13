from __future__ import annotations

from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from photon_action_memory import SCHEMA_VERSION
from photon_action_memory.api.client import SidecarClient
from photon_action_memory.api.server import create_app
from photon_action_memory.memory.store import SQLiteEventStore


def test_health_check_succeeds(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "schema_version": "action-memory.v1"}


def test_events_endpoint_stores_synthetic_event(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite")
    app = create_app(store)
    event = {
        "schema_version": SCHEMA_VERSION,
        "request_id": "req-events-1",
        "events": [
            {
                "schema_version": SCHEMA_VERSION,
                "event_id": "evt_synthetic_001",
                "event_type": "synthetic",
                "session_id": "session-1",
                "turn_id": "turn-1",
                "repo_id": "repo-1",
                "timestamp": "2026-04-30T12:00:00+00:00",
                "summary": "opened photon_action_memory/api/server.py",
            }
        ],
    }

    with TestClient(app) as client:
        response = client.post("/v1/events", json=event)

    assert response.status_code == 200
    assert response.json() == {
        "status": "stored",
        "event_id": "evt_synthetic_001",
        "stored": True,
    }
    assert store.count() == 1
    stored_event = store.list_events()[0]
    assert stored_event.payload["summary"] == "opened photon_action_memory/api/server.py"


def test_suggest_returns_no_model_fallback(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    request = {
        "schema_version": SCHEMA_VERSION,
        "request_id": "req-1",
        "agent": {"name": "codex"},
        "repo": {"root": str(tmp_path), "name": "photon-action-memory"},
        "task": {
            "user_request": "implement sidecar",
            "mode": "act",
            "summary": "implement sidecar",
        },
        "working_memory": {"touched_files": ["photon_action_memory/api/server.py"]},
        "recent_events": [
            {
                "type": "tool_result",
                "summary": "server.py contains the FastAPI entrypoint",
            }
        ],
        "budget": {"max_suggestions": 2, "max_evidence_chars": 80},
    }

    with TestClient(app) as client:
        response = client.post("/v1/suggest", json=request)

    payload = response.json()
    assert response.status_code == 200
    assert payload["request_id"] == "req-1"
    assert payload["model_version"] == "photon-action-memory-v0.1.0-fallback"
    assert payload["suggestions"][0]["kind"] == "read"
    assert payload["suggestions"][0]["target"] == "photon_action_memory/api/server.py"
    assert payload["warnings"] == [
        {
            "kind": "model_unavailable",
            "message": (
                "PHOTON model scoring is unavailable; deterministic fallback suggestions were used."
            ),
        }
    ]


def test_summarize_empty_payload_returns_422(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))

    with TestClient(app) as client:
        summarize_response = client.post("/v1/summarize", json={})

    assert summarize_response.status_code == 422


def test_summarize_minimum_valid_payload_returns_not_implemented_envelope(
    tmp_path: Path,
) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    payload = {
        "schema_version": "action-memory.v0.2",
        "request_id": "summarize-001",
    }

    with TestClient(app) as client:
        response = client.post("/v1/summarize", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "action-memory.v0.2"
    assert body["request_id"] == "summarize-001"
    assert body["sidecar_status"] == "not_implemented"
    assert body["summary"] is None
    assert body["validation"] is None
    assert body["warnings"][0]["kind"] == "not_implemented"


def test_summarize_full_anvil_turn_payload_validates(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    payload = {
        "schema_version": "action-memory.v0.2",
        "request_id": "summarize-turn-007",
        "session_id": "sess-1",
        "turn_id": "turn-7",
        "agent": {"name": "anvil", "version": "0.4.0-rc1"},
        "repo": {"root": str(tmp_path), "name": "demo"},
        "task": {"user_request": "fix session test", "mode": "act"},
        "summary_level": "turn",
        "chunk_ids": ["chunk_017", "chunk_018"],
        "recent_event_ids": ["evt_041", "evt_052"],
        "policy": {
            "require_evidence_ids": True,
            "max_facts": 8,
        },
    }

    with TestClient(app) as client:
        response = client.post("/v1/summarize", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "summarize-turn-007"
    assert body["sidecar_status"] == "not_implemented"


def test_evaluate_returns_ok_for_valid_request(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))

    with TestClient(app) as client:
        evaluate_response = client.post(
            "/v1/evaluate",
            json={
                "schema_version": "action-memory.v0.2",
                "request_id": "sidecar-eval-001",
            },
        )

    assert evaluate_response.status_code == 200
    data = evaluate_response.json()
    assert data["logged"] == 0
    assert data["status"] == "ok"


def test_client_suggest_fails_open_on_sidecar_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    transport = httpx.MockTransport(handler)
    with SidecarClient(transport=transport) as client:
        payload = client.suggest({"request_id": "req-timeout"})

    assert payload["request_id"] == "req-timeout"
    assert payload["suggestions"] == []
    assert payload["warnings"][0]["kind"] == "sidecar_unavailable"
