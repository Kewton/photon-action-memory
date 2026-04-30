from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from photon_action_memory import SCHEMA_VERSION
from photon_action_memory.memory.store import EventStore


def test_synthetic_event_round_trips_from_temp_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "events.sqlite"
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": "event-1",
        "session_id": "session-1",
        "turn_id": "turn-1",
        "repo_id": "repo-1",
        "timestamp": "2026-04-30T12:00:00+00:00",
        "event_type": "synthetic",
        "tool_name": "pytest",
        "status": "ok",
        "summary": "synthetic event",
        "artifacts": [{"path": "src/session/store.rs"}],
    }

    with EventStore(db_path) as store:
        stored = store.append_event(event)
        loaded = store.list_events(session_id="session-1")

    assert stored.event_id == "event-1"
    assert loaded == [stored]
    assert loaded[0].schema_version == SCHEMA_VERSION
    assert loaded[0].session_id == "session-1"
    assert loaded[0].turn_id == "turn-1"
    assert loaded[0].repo_id == "repo-1"
    assert loaded[0].timestamp == "2026-04-30T12:00:00+00:00"
    assert loaded[0].payload["redaction_status"] == "clean"


def test_event_store_persists_only_sanitized_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "events.sqlite"
    raw_secret = "sk-testsecret1234567890"
    raw_path = "/Users/alice/work/private/repo/main.py"
    event = {
        "event_id": "event-privacy",
        "session_id": "session-privacy",
        "turn_id": "turn-privacy",
        "repo_id": "repo-privacy",
        "timestamp": "2026-04-30T12:01:00+00:00",
        "event_type": "synthetic",
        "summary": f"opened {raw_path} with token={raw_secret}",
        "artifacts": [{"path": raw_path, "metadata": {"authorization": f"Bearer {raw_secret}"}}],
    }

    with EventStore(db_path) as store:
        stored = store.append_event(event)

    with sqlite3.connect(db_path) as connection:
        payload_json = connection.execute("SELECT payload_json FROM events").fetchone()[0]

    payload = json.loads(payload_json)
    assert payload == stored.payload
    assert raw_secret not in payload_json
    assert raw_path not in payload_json
    assert "[REDACTED_SECRET]" in payload_json
    assert "[ABS_PATH]/main.py" in payload_json
    assert payload["redaction_status"] == "redacted"


def test_event_store_requires_core_event_fields(tmp_path: Path) -> None:
    with EventStore(tmp_path / "events.sqlite") as store:
        with pytest.raises(ValueError, match="session_id"):
            store.append_event(
                {
                    "event_id": "event-missing",
                    "turn_id": "turn-1",
                    "repo_id": "repo-1",
                    "event_type": "synthetic",
                }
            )
