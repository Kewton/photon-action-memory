from __future__ import annotations

from pathlib import Path

import httpx
from fastapi.testclient import TestClient

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
        "event_id": "evt_synthetic_001",
        "event_type": "synthetic",
        "session_id": "session-1",
        "summary": "opened photon_action_memory/api/server.py",
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
        "request_id": "req-1",
        "task": {"summary": "implement sidecar"},
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


def test_summarize_and_evaluate_are_m2_stubs(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))

    with TestClient(app) as client:
        summarize_response = client.post("/v1/summarize", json={})
        evaluate_response = client.post("/v1/evaluate", json={})

    assert summarize_response.status_code == 501
    assert evaluate_response.status_code == 501


def test_client_suggest_fails_open_on_sidecar_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    transport = httpx.MockTransport(handler)
    with SidecarClient(transport=transport) as client:
        payload = client.suggest({"request_id": "req-timeout"})

    assert payload["request_id"] == "req-timeout"
    assert payload["suggestions"] == []
    assert payload["warnings"][0]["kind"] == "sidecar_unavailable"
