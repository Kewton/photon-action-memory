"""Anvil evaluate endpoint tests (Issue #70 P7).

Tests /v1/evaluate with Anvil-specific shadow/canary statuses:
- Shadow evaluate fixture stores correctly in SQLite
- Canary evaluate fixtures aggregate correctly
- raw_stdout/raw_stderr in evaluate request body are not stored
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from photon_action_memory.api.schema_v2 import DEFAULT_SCHEMA_VERSION_V2
from photon_action_memory.api.server import create_app
from photon_action_memory.eval.context_pack_log import (
    aggregate_context_pack_eval,
)
from photon_action_memory.memory.store import SQLiteEventStore

FIXTURES_V2 = Path(__file__).parent / "fixtures" / "v0.2"
FIXTURES_PHOTON = Path(__file__).parent / "fixtures" / "photon"


def _load(directory: Path, name: str) -> object:
    return json.loads((directory / name).read_text(encoding="utf-8"))


def _make_client(tmp_path: Path) -> tuple[TestClient, SQLiteEventStore]:
    store = SQLiteEventStore(tmp_path / "events.sqlite")
    return TestClient(create_app(store)), store


# ---------------------------------------------------------------------------
# Shadow evaluate fixture — HTTP endpoint storage
# ---------------------------------------------------------------------------


def test_anvil_shadow_evaluate_fixture_logs_ok(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    raw = _load(FIXTURES_V2, "evaluate_anvil_shadow.json")
    resp = client.post("/v1/evaluate", json=raw)
    assert resp.status_code == 200
    data = resp.json()
    assert data["logged"] == 1
    assert data["status"] == "ok"


def test_anvil_shadow_evaluate_fixture_payload_stored(tmp_path: Path) -> None:
    client, store = _make_client(tmp_path)
    raw = _load(FIXTURES_V2, "evaluate_anvil_shadow.json")
    client.post("/v1/evaluate", json=raw)
    assert store.count() == 1
    stored = store.list_events()[0]
    assert stored.payload["adoption_status"] == "shadow_not_injected"
    assert stored.payload["ignored_reason"] == "shadow_mode_no_injection"


def test_anvil_shadow_evaluate_raw_stdout_not_stored(tmp_path: Path) -> None:
    client, store = _make_client(tmp_path)
    body = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "anvil-eval-raw-001",
        "context_pack_event": {
            "context_pack_request_id": "pack-anvil-raw-001",
            "adoption_status": "shadow_not_injected",
            "items_adopted_count": 0,
            "items_ignored_count": 0,
            "raw_stdout": "huge build log line 1\nline 2\nline 3",
            "raw_stderr": "warning: unused import",
        },
    }
    resp = client.post("/v1/evaluate", json=body)
    assert resp.status_code == 200
    assert resp.json()["logged"] == 1
    stored = store.list_events()[0]
    assert "raw_stdout" not in stored.payload
    assert "raw_stderr" not in stored.payload
    assert stored.payload["adoption_status"] == "shadow_not_injected"


# ---------------------------------------------------------------------------
# Canary evaluate fixtures — aggregate shadow/canary statuses
# ---------------------------------------------------------------------------


def test_anvil_canary_evaluate_shadow_mode_fixture_aggregates(tmp_path: Path) -> None:
    client, store = _make_client(tmp_path)
    raw = _load(FIXTURES_V2, "canary_evaluate_shadow_mode.json")
    resp = client.post("/v1/evaluate", json=raw)
    assert resp.status_code == 200
    assert resp.json()["logged"] == 1
    payloads = [e.payload for e in store.list_events()]
    report = aggregate_context_pack_eval(payloads)
    assert report.total_turns == 1
    assert report.partial_count == 1


def test_anvil_shadow_evaluate_log_all_records_stored(tmp_path: Path) -> None:
    client, store = _make_client(tmp_path)
    photon_log = _load(FIXTURES_PHOTON, "anvil_shadow_evaluate_log.json")
    records = photon_log["records"]  # type: ignore[index]
    for i, record in enumerate(records):
        body = {
            "schema_version": DEFAULT_SCHEMA_VERSION_V2,
            "request_id": f"anvil-log-eval-{i}",
            "context_pack_event": record,
        }
        resp = client.post("/v1/evaluate", json=body)
        assert resp.status_code == 200
        assert resp.json()["logged"] == 1
    assert store.count() == 3


def test_anvil_shadow_evaluate_log_aggregates_correctly(tmp_path: Path) -> None:
    client, store = _make_client(tmp_path)
    photon_log = _load(FIXTURES_PHOTON, "anvil_shadow_evaluate_log.json")
    records = photon_log["records"]  # type: ignore[index]
    for i, record in enumerate(records):
        client.post(
            "/v1/evaluate",
            json={
                "schema_version": DEFAULT_SCHEMA_VERSION_V2,
                "request_id": f"anvil-agg-eval-{i}",
                "context_pack_event": record,
            },
        )
    payloads = [e.payload for e in store.list_events()]
    report = aggregate_context_pack_eval(payloads)
    assert report.total_turns == 3
    assert report.shadow_not_injected_count == 1
    assert report.not_available_count == 1
    assert report.adopted_count == 1
    assert report.adoption_rate == pytest.approx(1 / 3)


def test_anvil_evaluate_canary_context_pack_adopted_fixture_logs(tmp_path: Path) -> None:
    client, store = _make_client(tmp_path)
    raw = _load(FIXTURES_V2, "evaluate_context_pack_adopted.json")
    resp = client.post("/v1/evaluate", json=raw)
    assert resp.status_code == 200
    assert resp.json()["logged"] == 1
    stored = store.list_events()[0]
    assert stored.payload["adoption_status"] == "adopted"
