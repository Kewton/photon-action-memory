from __future__ import annotations

from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from photon_action_memory import SCHEMA_VERSION
from photon_action_memory.api.client import SidecarClient
from photon_action_memory.api.schema_v2 import DEFAULT_SCHEMA_VERSION_V2
from photon_action_memory.api.server import create_app
from photon_action_memory.memory.store import SQLiteEventStore
from photon_action_memory.memory.summary_store import SummaryStore


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


def _summarize_request(
    *,
    request_id: str,
    session_id: str | None = None,
    repo_id: str | None = None,
    task_signature: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": request_id,
    }
    if session_id is not None:
        payload["session_id"] = session_id
    if repo_id is not None:
        payload["repo_id"] = repo_id
    if task_signature is not None:
        payload["task_signature"] = task_signature
    return payload


def _seed_event(
    *,
    event_id: str,
    session_id: str = "session-summarize-1",
    turn_id: str = "turn-summarize-1",
    repo_id: str = "repo-summarize-1",
    event_type: str = "file_read",
    summary: str = "read photon_action_memory/api/server.py",
    outcome: str = "useful",
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "event_type": event_type,
        "session_id": session_id,
        "turn_id": turn_id,
        "repo_id": repo_id,
        "timestamp": "2026-04-30T12:00:00+00:00",
        "summary": summary,
        "outcome": outcome,
        "redaction_status": "clean",
    }


def test_summarize_empty_payload_returns_422(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))

    with TestClient(app) as client:
        summarize_response = client.post("/v1/summarize", json={})

    assert summarize_response.status_code == 422


def test_summarize_returns_ok_for_empty_store(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))

    with TestClient(app) as client:
        response = client.post(
            "/v1/summarize",
            json=_summarize_request(request_id="sum-empty-1"),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["sidecar_status"] == "ok"
    assert data["status"] == "ok"
    assert data["chunks_built"] == 0
    assert data["summaries_upserted"] == 0
    assert data["summary_ids"] == []
    assert data["summary"] is None


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
    assert body["sidecar_status"] == "ok"
    assert body["status"] == "ok"
    assert body["summary_ids"] == []
    assert body["summary"] is None


def test_summarize_builds_and_persists_summary(tmp_path: Path) -> None:
    event_store = SQLiteEventStore(tmp_path / "events.sqlite")
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    app = create_app(event_store, summary_store)

    events = [
        _seed_event(event_id="evt-sum-a", repo_id="repo-A"),
        _seed_event(event_id="evt-sum-b", repo_id="repo-A"),
    ]
    with TestClient(app) as client:
        ingest = client.post(
            "/v1/events",
            json={
                "schema_version": SCHEMA_VERSION,
                "request_id": "req-ingest-1",
                "events": events,
            },
        )
        assert ingest.status_code == 200

        response = client.post(
            "/v1/summarize",
            json=_summarize_request(
                request_id="sum-build-1",
                repo_id="repo-A",
                task_signature="task-A",
            ),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["sidecar_status"] == "ok"
    assert data["status"] == "ok"
    assert data["chunks_built"] == 1
    assert data["summaries_upserted"] == 1
    assert data["summary"] is not None
    assert summary_store.count() == 1
    summary = summary_store.get(data["summary_ids"][0])
    assert summary is not None
    assert summary.repo_id == "repo-A"
    assert summary.task_signature == "task-A"
    assert set(summary.source_chunk_ids)  # at least one chunk recorded
    assert any("evt-sum-a" in done.evidence_ids for done in summary.actions_done)


def test_summarize_then_context_pack_returns_summary(tmp_path: Path) -> None:
    event_store = SQLiteEventStore(tmp_path / "events.sqlite")
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    app = create_app(event_store, summary_store)

    events = [
        _seed_event(event_id="evt-pack-a", repo_id="repo-pack"),
        _seed_event(event_id="evt-pack-b", repo_id="repo-pack"),
    ]
    with TestClient(app) as client:
        client.post(
            "/v1/events",
            json={
                "schema_version": SCHEMA_VERSION,
                "request_id": "req-pack-ingest",
                "events": events,
            },
        )
        sum_resp = client.post(
            "/v1/summarize",
            json=_summarize_request(request_id="sum-pack-1", repo_id="repo-pack"),
        )
        assert sum_resp.status_code == 200
        new_summary_id = sum_resp.json()["summary_ids"][0]

        pack_resp = client.post(
            "/v1/context/pack",
            json={
                "schema_version": DEFAULT_SCHEMA_VERSION_V2,
                "request_id": "pack-after-summarize-1",
                "agent": {"name": "codex"},
                "repo": {"root": str(tmp_path), "name": "repo-pack"},
                "task": {
                    "user_request": "inspect server",
                    "mode": "act",
                    "summary": "inspect",
                },
                "working_memory": {"touched_files": []},
                "recent_event_ids": [],
                "candidate_summary_ids": [],
                "budget": {"max_memory_tokens": 800, "max_evidence_chars": 1200},
            },
        )

    assert pack_resp.status_code == 200
    data = pack_resp.json()
    item_ids = {item["id"] for item in data["context_pack"]["items"]}
    assert new_summary_id in item_ids


def test_summarize_is_idempotent_across_repeat_calls(tmp_path: Path) -> None:
    event_store = SQLiteEventStore(tmp_path / "events.sqlite")
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    app = create_app(event_store, summary_store)

    events = [
        _seed_event(event_id="evt-idem-a"),
        _seed_event(event_id="evt-idem-b"),
    ]
    with TestClient(app) as client:
        client.post(
            "/v1/events",
            json={
                "schema_version": SCHEMA_VERSION,
                "request_id": "req-idem-ingest",
                "events": events,
            },
        )
        first = client.post(
            "/v1/summarize",
            json=_summarize_request(request_id="sum-idem-1"),
        )
        second = client.post(
            "/v1/summarize",
            json=_summarize_request(request_id="sum-idem-2"),
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["summary_ids"] == second.json()["summary_ids"]
    assert summary_store.count() == first.json()["summaries_upserted"]


def test_summarize_filters_by_session_id(tmp_path: Path) -> None:
    event_store = SQLiteEventStore(tmp_path / "events.sqlite")
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    app = create_app(event_store, summary_store)

    events = [
        _seed_event(event_id="evt-sess-a", session_id="sess-A", turn_id="turn-A"),
        _seed_event(event_id="evt-sess-b", session_id="sess-B", turn_id="turn-B"),
    ]
    with TestClient(app) as client:
        client.post(
            "/v1/events",
            json={
                "schema_version": SCHEMA_VERSION,
                "request_id": "req-sess-ingest",
                "events": events,
            },
        )
        response = client.post(
            "/v1/summarize",
            json=_summarize_request(request_id="sum-sess-1", session_id="sess-A"),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["summaries_upserted"] == 1
    only_summary = summary_store.get(data["summary_ids"][0])
    assert only_summary is not None
    assert only_summary.session_id == "sess-A"


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
