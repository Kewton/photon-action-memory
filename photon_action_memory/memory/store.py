"""Local SQLite event store for sanitized agent events."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from photon_action_memory import SCHEMA_VERSION
from photon_action_memory.memory.sanitizer import SanitizedPayload, sanitize_event_payload


@dataclass(frozen=True)
class StoredEvent:
    """Event row returned by the local event store."""

    schema_version: str
    event_id: str
    session_id: str
    turn_id: str
    repo_id: str
    timestamp: str
    event_type: str
    payload: SanitizedPayload


class EventStore:
    """Append/read API for sanitized events in a local SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize_schema()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> EventStore:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def append_event(self, event: Mapping[str, Any]) -> StoredEvent:
        """Sanitize and persist one event, returning the stored representation."""
        sanitized = sanitize_event_payload(event)
        schema_version = _string_field(sanitized, "schema_version", default=SCHEMA_VERSION)
        event_id = _string_field(sanitized, "event_id", default_factory=lambda: str(uuid4()))
        session_id = _required_string_field(sanitized, "session_id")
        turn_id = _required_string_field(sanitized, "turn_id")
        repo_id = _required_string_field(sanitized, "repo_id")
        timestamp = _string_field(sanitized, "timestamp", default_factory=_utc_timestamp)
        event_type = _required_string_field(sanitized, "event_type")
        sanitized = {
            **sanitized,
            "schema_version": schema_version,
            "event_id": event_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "repo_id": repo_id,
            "timestamp": timestamp,
            "event_type": event_type,
        }
        stored = StoredEvent(
            schema_version=schema_version,
            event_id=event_id,
            session_id=session_id,
            turn_id=turn_id,
            repo_id=repo_id,
            timestamp=timestamp,
            event_type=event_type,
            payload=sanitized,
        )

        payload_json = _to_canonical_json(stored.payload)
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO events (
                    schema_version,
                    event_id,
                    session_id,
                    turn_id,
                    repo_id,
                    timestamp,
                    event_type,
                    payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stored.schema_version,
                    stored.event_id,
                    stored.session_id,
                    stored.turn_id,
                    stored.repo_id,
                    stored.timestamp,
                    stored.event_type,
                    payload_json,
                ),
            )
        return stored

    def list_events(
        self,
        *,
        session_id: str | None = None,
        repo_id: str | None = None,
        limit: int | None = None,
    ) -> list[StoredEvent]:
        """Read stored events ordered by timestamp and insertion id."""
        where_clauses: list[str] = []
        params: list[object] = []
        if session_id is not None:
            where_clauses.append("session_id = ?")
            params.append(session_id)
        if repo_id is not None:
            where_clauses.append("repo_id = ?")
            params.append(repo_id)

        query = "SELECT * FROM events"
        if where_clauses:
            query = f"{query} WHERE {' AND '.join(where_clauses)}"
        query = f"{query} ORDER BY timestamp ASC, id ASC"
        if limit is not None:
            if limit < 1:
                msg = "limit must be greater than zero"
                raise ValueError(msg)
            query = f"{query} LIMIT ?"
            params.append(limit)

        rows = self._connection.execute(query, params).fetchall()
        return [_stored_event_from_row(row) for row in rows]

    def count(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) AS count FROM events").fetchone()
        return int(row["count"])

    def _initialize_schema(self) -> None:
        with self._connection:
            columns = {
                str(row["name"])
                for row in self._connection.execute("PRAGMA table_info(events)").fetchall()
            }
            required_columns = {
                "schema_version",
                "event_id",
                "session_id",
                "turn_id",
                "repo_id",
                "timestamp",
                "event_type",
                "payload_json",
            }
            if columns and not required_columns.issubset(columns):
                self._connection.execute("DROP TABLE events")
            self._connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    schema_version TEXT NOT NULL,
                    event_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    repo_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_session_timestamp
                    ON events (session_id, timestamp);
                CREATE INDEX IF NOT EXISTS idx_events_repo_timestamp
                    ON events (repo_id, timestamp);
                """
            )


class SQLiteEventStore(EventStore):
    """Compatibility name used by the sidecar MVP."""

    def append(self, payload: Mapping[str, Any]) -> StoredEvent:
        return self.append_event(payload)


def _stored_event_from_row(row: sqlite3.Row) -> StoredEvent:
    payload = json.loads(row["payload_json"])
    if not isinstance(payload, dict):
        msg = "stored event payload must be a JSON object"
        raise TypeError(msg)
    return StoredEvent(
        schema_version=row["schema_version"],
        event_id=row["event_id"],
        session_id=row["session_id"],
        turn_id=row["turn_id"],
        repo_id=row["repo_id"],
        timestamp=row["timestamp"],
        event_type=row["event_type"],
        payload=payload,
    )


def _required_string_field(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value:
        msg = f"event field {field_name!r} is required"
        raise ValueError(msg)
    return value


def _string_field(
    payload: Mapping[str, Any],
    field_name: str,
    *,
    default: str | None = None,
    default_factory: Callable[[], str] | None = None,
) -> str:
    value = payload.get(field_name)
    if isinstance(value, str) and value:
        return value
    if default is not None:
        return default
    if default_factory is not None:
        return str(default_factory())
    msg = f"event field {field_name!r} is required"
    raise ValueError(msg)


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _to_canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


__all__ = ["EventStore", "SQLiteEventStore", "StoredEvent"]
