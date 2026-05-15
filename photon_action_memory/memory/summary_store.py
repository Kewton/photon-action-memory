"""SQLite-backed store for ActionSummary objects."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from photon_action_memory.api.schema_v2 import ActionSummary, UniversalFilters
from photon_action_memory.eval.summary_feedback import (
    SummaryFeedbackRecord,
    classify_outcome,
    is_adopted,
)


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

    def search_universal(
        self,
        *,
        filters: UniversalFilters | None = None,
        limit: int = 50,
    ) -> list[ActionSummary]:
        """Return universal-scope summaries matching detected context filters."""
        if limit < 1:
            msg = "limit must be >= 1"
            raise ValueError(msg)
        rows = self._connection.execute(
            """
            SELECT payload_json FROM action_summaries
            WHERE validity_status = 'valid'
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        summaries = [ActionSummary.model_validate_json(row["payload_json"]) for row in rows]
        universal = [
            summary
            for summary in summaries
            if summary.applicability_scope == "universal"
            and _matches_universal_filters(summary, filters)
        ]
        return sorted(universal, key=_universal_sort_key)

    def count(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) AS cnt FROM action_summaries").fetchone()
        return int(row["cnt"])

    def record_outcomes(
        self,
        summary_ids: Iterable[str],
        *,
        adoption_status: str,
        outcome: str | None,
        evidence_expand_requested: bool = False,
    ) -> int:
        """Update per-summary feedback counters from a single /v1/evaluate record.

        Returns the number of rows touched. Excluded statuses (``error``,
        ``not_available``, ``shadow_not_injected``) and empty ``summary_ids``
        are no-ops. ``adoption_count`` increments only when the record's
        status counts as adoption (``adopted`` / ``partial``).
        """
        is_quality, classification = classify_outcome(adoption_status, outcome)
        if not is_quality:
            return 0

        ids = [sid for sid in summary_ids if sid]
        if not ids:
            return 0

        success_inc = 1 if classification == "success" else 0
        failure_inc = 1 if classification == "failure" else 0
        safety_inc = 1 if classification == "safety" else 0
        adoption_inc = 1 if is_adopted(adoption_status) else 0
        expand_inc = 1 if evidence_expand_requested else 0
        now = datetime.now(UTC).isoformat(timespec="microseconds")

        rows_touched = 0
        with self._connection:
            for sid in ids:
                self._connection.execute(
                    """
                    INSERT INTO summary_feedback (
                        summary_id, adoption_count, success_count, failure_count,
                        safety_violation_count, expand_request_count, quality_turns,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(summary_id) DO UPDATE SET
                        adoption_count         = adoption_count         + ?,
                        success_count          = success_count          + ?,
                        failure_count          = failure_count          + ?,
                        safety_violation_count = safety_violation_count + ?,
                        expand_request_count   = expand_request_count   + ?,
                        quality_turns          = quality_turns          + 1,
                        updated_at             = ?
                    """,
                    (
                        sid,
                        adoption_inc,
                        success_inc,
                        failure_inc,
                        safety_inc,
                        expand_inc,
                        now,
                        adoption_inc,
                        success_inc,
                        failure_inc,
                        safety_inc,
                        expand_inc,
                        now,
                    ),
                )
                rows_touched += 1
        return rows_touched

    def get_feedback(self, summary_id: str) -> SummaryFeedbackRecord | None:
        row = self._connection.execute(
            """
            SELECT summary_id, adoption_count, success_count, failure_count,
                   safety_violation_count, expand_request_count, quality_turns
            FROM summary_feedback WHERE summary_id = ?
            """,
            (summary_id,),
        ).fetchone()
        return _row_to_feedback(row)

    def get_feedback_map(
        self,
        summary_ids: Iterable[str],
    ) -> dict[str, SummaryFeedbackRecord]:
        """Return feedback records keyed by summary_id; missing IDs are omitted."""
        ids = [sid for sid in summary_ids if sid]
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        rows = self._connection.execute(
            f"""
            SELECT summary_id, adoption_count, success_count, failure_count,
                   safety_violation_count, expand_request_count, quality_turns
            FROM summary_feedback WHERE summary_id IN ({placeholders})
            """,
            ids,
        ).fetchall()
        result: dict[str, SummaryFeedbackRecord] = {}
        for row in rows:
            record = _row_to_feedback(row)
            if record is not None:
                result[record.summary_id] = record
        return result

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
                CREATE TABLE IF NOT EXISTS summary_feedback (
                    summary_id              TEXT PRIMARY KEY,
                    adoption_count          INTEGER NOT NULL DEFAULT 0,
                    success_count           INTEGER NOT NULL DEFAULT 0,
                    failure_count           INTEGER NOT NULL DEFAULT 0,
                    safety_violation_count  INTEGER NOT NULL DEFAULT 0,
                    expand_request_count    INTEGER NOT NULL DEFAULT 0,
                    quality_turns           INTEGER NOT NULL DEFAULT 0,
                    updated_at              TEXT NOT NULL
                );
                """
            )


def _row_to_feedback(row: sqlite3.Row | None) -> SummaryFeedbackRecord | None:
    if row is None:
        return None
    return SummaryFeedbackRecord(
        summary_id=row["summary_id"],
        adoption_count=int(row["adoption_count"]),
        success_count=int(row["success_count"]),
        failure_count=int(row["failure_count"]),
        safety_violation_count=int(row["safety_violation_count"]),
        expand_request_count=int(row["expand_request_count"]),
        quality_turns=int(row["quality_turns"]),
    )


def _matches_universal_filters(
    summary: ActionSummary,
    filters: UniversalFilters | None,
) -> bool:
    metadata = summary.universal_metadata
    if metadata is None:
        return True
    wanted = filters or UniversalFilters()
    fields = ("language", "framework", "tool", "os")
    has_declared_filter = False
    has_match = False
    for field in fields:
        declared = _lower_set(getattr(metadata, field) or [])
        if not declared:
            continue
        has_declared_filter = True
        requested = _lower_set(getattr(wanted, field))
        if declared & requested:
            has_match = True
    if not has_declared_filter:
        return True
    return has_match


def _lower_set(values: list[str]) -> set[str]:
    return {value.strip().lower() for value in values if value.strip()}


def _universal_sort_key(summary: ActionSummary) -> tuple[int, str]:
    severity = "info"
    if summary.universal_metadata is not None:
        severity = str(summary.universal_metadata.severity).lower()
    priority = {"critical": 0, "warning": 1, "info": 2}.get(severity, 2)
    return (priority, summary.summary_id)


__all__ = ["SummaryStore"]
