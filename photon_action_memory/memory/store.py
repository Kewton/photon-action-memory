"""Local SQLite event store for sidecar events."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from photon_action_memory.memory.sanitizer import sanitize_text


@dataclass(frozen=True)
class StoredEvent:
    event_id: str
    received_at: str
    payload: dict[str, Any]


class SQLiteEventStore:
    """Append-only SQLite store for JSON event payloads."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def append(self, payload: dict[str, Any]) -> StoredEvent:
        sanitized_payload = _sanitize_payload(payload)
        event_id = _coerce_event_id(sanitized_payload.get("event_id"))
        sanitized_payload["event_id"] = event_id
        received_at = datetime.now(UTC).isoformat()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO events (event_id, received_at, payload_json)
                VALUES (?, ?, ?)
                """,
                (
                    event_id,
                    received_at,
                    json.dumps(sanitized_payload, sort_keys=True, separators=(",", ":")),
                ),
            )

        return StoredEvent(event_id=event_id, received_at=received_at, payload=sanitized_payload)

    def list_events(self, *, limit: int = 100) -> list[StoredEvent]:
        safe_limit = max(0, limit)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, received_at, payload_json
                FROM events
                ORDER BY received_at ASC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()

        return [
            StoredEvent(
                event_id=str(row["event_id"]),
                received_at=str(row["received_at"]),
                payload=dict(json.loads(str(row["payload_json"]))),
            )
            for row in rows
        ]

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM events").fetchone()
        return int(row["count"])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    received_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )


def _coerce_event_id(value: object) -> str:
    if isinstance(value, str) and value:
        return value
    return f"evt_{uuid4().hex}"


def _sanitize_payload(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize_payload(item) for key, item in value.items()}
    return value
