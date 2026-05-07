"""SQLite-backed store for ActionSummary objects."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from photon_action_memory.api.schema_v2 import ActionSummary


class SummaryStore:
    """Upsert / retrieve ActionSummary objects in a local SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize_schema()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SummaryStore:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def upsert(self, summary: ActionSummary) -> None:
        """Insert or update an ActionSummary row keyed by summary_id."""
        now = datetime.now(UTC).isoformat(timespec="microseconds")
        payload_json = summary.model_dump_json()
        row = self._connection.execute(
            "SELECT created_at FROM action_summaries WHERE summary_id = ?",
            (summary.summary_id,),
        ).fetchone()
        created_at = row["created_at"] if row else now
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO action_summaries
                    (summary_id, repo_id, task_signature, validity_status,
                     created_at, updated_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(summary_id) DO UPDATE SET
                    repo_id            = excluded.repo_id,
                    task_signature     = excluded.task_signature,
                    validity_status    = excluded.validity_status,
                    updated_at         = excluded.updated_at,
                    payload_json       = excluded.payload_json
                """,
                (
                    summary.summary_id,
                    summary.repo_id,
                    summary.task_signature,
                    summary.validity.status,
                    created_at,
                    now,
                    payload_json,
                ),
            )

    def get(self, summary_id: str) -> ActionSummary | None:
        """Return a single summary by ID, or None if not found."""
        row = self._connection.execute(
            "SELECT payload_json FROM action_summaries WHERE summary_id = ?",
            (summary_id,),
        ).fetchone()
        if row is None:
            return None
        return ActionSummary.model_validate_json(row["payload_json"])

    def resolve(self, summary_ids: list[str]) -> list[ActionSummary]:
        """Return summaries for the given IDs in input order; missing IDs are skipped."""
        if not summary_ids:
            return []
        placeholders = ",".join("?" * len(summary_ids))
        rows = self._connection.execute(
            f"SELECT summary_id, payload_json FROM action_summaries"
            f" WHERE summary_id IN ({placeholders})",
            summary_ids,
        ).fetchall()
        by_id = {
            row["summary_id"]: ActionSummary.model_validate_json(row["payload_json"])
            for row in rows
        }
        return [by_id[sid] for sid in summary_ids if sid in by_id]

    def search(
        self,
        *,
        repo_id: str | None = None,
        task_signature: str | None = None,
        limit: int = 50,
    ) -> list[ActionSummary]:
        """Return summaries matching repo/task conditions, ordered by recency."""
        if limit < 1:
            msg = "limit must be >= 1"
            raise ValueError(msg)
        where_clauses: list[str] = []
        params: list[object] = []
        if repo_id is not None:
            where_clauses.append("repo_id = ?")
            params.append(repo_id)
        if task_signature is not None:
            where_clauses.append("task_signature = ?")
            params.append(task_signature)
        query = "SELECT payload_json FROM action_summaries"
        if where_clauses:
            query = f"{query} WHERE {' AND '.join(where_clauses)}"
        query = f"{query} ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        rows = self._connection.execute(query, params).fetchall()
        return [ActionSummary.model_validate_json(row["payload_json"]) for row in rows]

    def count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS cnt FROM action_summaries"
        ).fetchone()
        return int(row["cnt"])

    def _initialize_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS action_summaries (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    summary_id      TEXT NOT NULL UNIQUE,
                    repo_id         TEXT,
                    task_signature  TEXT,
                    validity_status TEXT NOT NULL DEFAULT 'valid',
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL,
                    payload_json    TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_summaries_repo
                    ON action_summaries (repo_id);
                CREATE INDEX IF NOT EXISTS idx_summaries_task
                    ON action_summaries (task_signature);
                CREATE INDEX IF NOT EXISTS idx_summaries_validity
                    ON action_summaries (validity_status);
                """
            )


__all__ = ["SummaryStore"]
