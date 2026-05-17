"""Issue #126 — ``context_pack_ranking_log`` records and label classifier.

The ranking log captures, per ``/v1/context/pack`` response, which candidates
were exposed to the agent (admitted) versus which were dropped by an upstream
quality / safety gate or by the token budget. It deliberately stores only
identifiers, positions, scores, and gate reasons — never rendered text, never
raw evidence content, never prompt text.

After ``/v1/evaluate`` records adoption outcomes, ``update_outcomes`` annotates
the matching log rows with the resolved ``outcome_family`` so the Phase 2
checkpoint builder can map ``(admission state, outcome_family)`` pairs into the
correct training label.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, cast

LABEL_ADOPTED_SUCCESS = "adopted_success"
LABEL_ADOPTED_FAILURE = "adopted_failure"
LABEL_ADOPTED_SAFETY = "adopted_safety"
LABEL_IGNORED = "ignored"
LABEL_PARTIAL = "partial"
LABEL_NOT_SELECTED = "not_selected"
LABEL_OMITTED_BY_GATE = "omitted_by_gate"

ALL_LABELS: frozenset[str] = frozenset(
    {
        LABEL_ADOPTED_SUCCESS,
        LABEL_ADOPTED_FAILURE,
        LABEL_ADOPTED_SAFETY,
        LABEL_IGNORED,
        LABEL_PARTIAL,
        LABEL_NOT_SELECTED,
        LABEL_OMITTED_BY_GATE,
    }
)

OutcomeFamily = Literal["success", "failure", "safety", "unknown"]

# Reasons returned by ContextAdmissionController that should be classified as
# gate omissions (the candidate was actively rejected by a quality/safety/
# stale-data gate rather than merely missing the budget cut).
_GATE_OMISSION_TOKENS: tuple[str, ...] = (
    "quality",
    "safety",
    "stale",
    "contradict",
    "answer_leak",
    "disabled",
    "denied",
    "raw_tool_log",
    "premature",
)

_SUCCESS_OUTCOMES: frozenset[str] = frozenset(
    {"success", "accepted", "completed", "user_positive", "user_rule"}
)
_SAFETY_OUTCOMES: frozenset[str] = frozenset({"safety_violation", "unsafe", "harmful"})


@dataclass(frozen=True)
class RankingLogEntry:
    """One ``(context_pack_request, candidate)`` row to persist.

    The Phase 1 ranking log captures only identifiers, position, score,
    selection state, and the *machine-readable* reason a candidate was
    omitted. Prompt-visible text and raw content are intentionally absent
    so the table is safe to re-use as training data.
    """

    context_pack_request_id: str
    summary_id: str
    kind: str = "action_summary"
    position: int = 0
    score: float = 0.0
    selected: bool = False
    omitted_reason: str | None = None


@dataclass(frozen=True)
class StoredRankingLogEntry:
    """A ``RankingLogEntry`` read back from storage with its resolved label."""

    context_pack_request_id: str
    summary_id: str
    kind: str
    position: int
    score: float
    selected: bool
    omitted_reason: str | None
    outcome_family: OutcomeFamily | None
    adoption_status: str | None
    created_at: str

    def label(self) -> str:
        return classify_label(
            selected=self.selected,
            omitted_reason=self.omitted_reason,
            outcome_family=self.outcome_family,
            adoption_status=self.adoption_status,
        )


@dataclass(frozen=True)
class RankingLogOutcome:
    """Outcome annotation written back to the log by ``/v1/evaluate``."""

    context_pack_request_id: str
    summary_id: str
    outcome_family: OutcomeFamily
    adoption_status: str


def outcome_family_from_record(
    *,
    adoption_status: str | None,
    outcome: str | None,
) -> OutcomeFamily:
    """Map an /v1/evaluate (adoption_status, outcome) pair to an outcome family."""
    if outcome in _SAFETY_OUTCOMES:
        return "safety"
    if outcome in _SUCCESS_OUTCOMES:
        return "success"
    if outcome in (None, "", "unknown"):
        # No explicit outcome — treat partial as unknown so it weights as a
        # weak signal rather than a confirmed failure.
        if adoption_status == "partial":
            return "unknown"
        if adoption_status == "ignored":
            return "failure"
        return "unknown"
    return "failure"


def classify_label(
    *,
    selected: bool,
    omitted_reason: str | None,
    outcome_family: OutcomeFamily | None,
    adoption_status: str | None,
) -> str:
    """Return one of the Phase 1 label strings for a ranking log row."""
    if not selected:
        if omitted_reason and _is_gate_reason(omitted_reason):
            return LABEL_OMITTED_BY_GATE
        return LABEL_NOT_SELECTED
    if adoption_status == "partial":
        return LABEL_PARTIAL
    if outcome_family == "success":
        return LABEL_ADOPTED_SUCCESS
    if outcome_family == "failure":
        return LABEL_ADOPTED_FAILURE
    if outcome_family == "safety":
        return LABEL_ADOPTED_SAFETY
    if adoption_status == "ignored":
        return LABEL_IGNORED
    # Adopted but no outcome captured yet — treat as ignored so weak-negative
    # weighting kicks in and the builder doesn't fabricate a success signal.
    return LABEL_IGNORED


def _is_gate_reason(reason: str) -> bool:
    lowered = reason.lower()
    return any(token in lowered for token in _GATE_OMISSION_TOKENS)


@dataclass
class RankingLogStore:
    """SQLite-backed writer/reader for ``context_pack_ranking_log`` rows.

    The store owns its table schema and can be created against an existing
    :class:`sqlite3.Connection` (typically the connection used by
    :class:`SummaryStore` so the per-summary feedback table and the ranking
    log live in the same database file).
    """

    connection: sqlite3.Connection
    table: str = "context_pack_ranking_log"
    _initialized: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        if self._initialized:
            return
        with self.connection:
            self.connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table} (
                    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                    context_pack_request_id  TEXT NOT NULL,
                    summary_id               TEXT NOT NULL,
                    kind                     TEXT NOT NULL DEFAULT 'action_summary',
                    position                 INTEGER NOT NULL DEFAULT 0,
                    score                    REAL NOT NULL DEFAULT 0.0,
                    selected                 INTEGER NOT NULL DEFAULT 0,
                    omitted_reason           TEXT,
                    outcome_family           TEXT,
                    adoption_status          TEXT,
                    created_at               TEXT NOT NULL,
                    UNIQUE (context_pack_request_id, summary_id, kind)
                )
                """
            )
            self.connection.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.table}_request "
                f"ON {self.table} (context_pack_request_id)"
            )
            self.connection.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.table}_summary ON {self.table} (summary_id)"
            )
        self._initialized = True

    def record_entries(self, entries: Iterable[RankingLogEntry]) -> int:
        """Insert one batch of ranking-log rows for a single context_pack call.

        Returns the number of rows inserted (duplicates are ignored to keep
        the call idempotent under retries).
        """
        rows = 0
        now = _utc_now()
        with self.connection:
            for entry in entries:
                if not entry.context_pack_request_id or not entry.summary_id:
                    continue
                _assert_text_safe(entry.omitted_reason)
                self.connection.execute(
                    f"""
                    INSERT INTO {self.table} (
                        context_pack_request_id,
                        summary_id,
                        kind,
                        position,
                        score,
                        selected,
                        omitted_reason,
                        outcome_family,
                        adoption_status,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(context_pack_request_id, summary_id, kind)
                    DO NOTHING
                    """,
                    (
                        entry.context_pack_request_id,
                        entry.summary_id,
                        entry.kind,
                        int(entry.position),
                        float(entry.score),
                        1 if entry.selected else 0,
                        entry.omitted_reason,
                        None,
                        None,
                        now,
                    ),
                )
                rows += 1
        return rows

    def update_outcomes(self, outcomes: Sequence[RankingLogOutcome]) -> int:
        """Write outcome_family / adoption_status back from /v1/evaluate.

        Only rows that were previously logged are touched; missing
        ``(context_pack_request_id, summary_id)`` pairs are ignored. Returns
        the number of rows updated.
        """
        if not outcomes:
            return 0
        updated = 0
        with self.connection:
            for record in outcomes:
                cursor = self.connection.execute(
                    f"""
                    UPDATE {self.table}
                    SET outcome_family = ?,
                        adoption_status = ?
                    WHERE context_pack_request_id = ?
                      AND summary_id = ?
                    """,
                    (
                        record.outcome_family,
                        record.adoption_status,
                        record.context_pack_request_id,
                        record.summary_id,
                    ),
                )
                updated += cursor.rowcount or 0
        return updated

    def iter_entries(
        self,
        *,
        context_pack_request_id: str | None = None,
        limit: int | None = None,
    ) -> list[StoredRankingLogEntry]:
        """Read entries back, optionally scoped to one request."""
        query = f"""
            SELECT context_pack_request_id,
                   summary_id,
                   kind,
                   position,
                   score,
                   selected,
                   omitted_reason,
                   outcome_family,
                   adoption_status,
                   created_at
            FROM {self.table}
        """
        params: list[object] = []
        if context_pack_request_id is not None:
            query += " WHERE context_pack_request_id = ?"
            params.append(context_pack_request_id)
        query += " ORDER BY id ASC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))
        rows = self.connection.execute(query, params).fetchall()
        return [_row_to_stored_entry(row) for row in rows]

    def latest_updated_at(self) -> str | None:
        row = self.connection.execute(
            f"SELECT MAX(created_at) AS latest FROM {self.table}"
        ).fetchone()
        if row is None:
            return None
        latest = row["latest"] if isinstance(row, sqlite3.Row) else row[0]
        return str(latest) if latest else None


def _row_to_stored_entry(row: sqlite3.Row | tuple[object, ...]) -> StoredRankingLogEntry:
    keys = (
        "context_pack_request_id",
        "summary_id",
        "kind",
        "position",
        "score",
        "selected",
        "omitted_reason",
        "outcome_family",
        "adoption_status",
        "created_at",
    )
    if isinstance(row, sqlite3.Row):
        values: dict[str, object] = {key: row[key] for key in keys}
    else:
        values = dict(zip(keys, row, strict=False))
    outcome_family_raw = values.get("outcome_family")
    outcome_family: OutcomeFamily | None = None
    if outcome_family_raw == "success":
        outcome_family = "success"
    elif outcome_family_raw == "failure":
        outcome_family = "failure"
    elif outcome_family_raw == "safety":
        outcome_family = "safety"
    elif outcome_family_raw == "unknown":
        outcome_family = "unknown"
    omitted_reason = values.get("omitted_reason")
    adoption_status = values.get("adoption_status")
    return StoredRankingLogEntry(
        context_pack_request_id=str(values["context_pack_request_id"]),
        summary_id=str(values["summary_id"]),
        kind=str(values["kind"]),
        position=int(cast(str | int | float, values["position"])),
        score=float(cast(str | int | float, values["score"])),
        selected=bool(values["selected"]),
        omitted_reason=str(omitted_reason) if omitted_reason is not None else None,
        outcome_family=outcome_family,
        adoption_status=str(adoption_status) if adoption_status is not None else None,
        created_at=str(values["created_at"]),
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _assert_text_safe(value: str | None) -> None:
    """Defence-in-depth check: reject obviously-rendered prompt text."""
    if value is None:
        return
    if len(value) > 200:
        raise ValueError("ranking log omitted_reason must be a short machine-readable token")


__all__ = [
    "ALL_LABELS",
    "LABEL_ADOPTED_FAILURE",
    "LABEL_ADOPTED_SAFETY",
    "LABEL_ADOPTED_SUCCESS",
    "LABEL_IGNORED",
    "LABEL_NOT_SELECTED",
    "LABEL_OMITTED_BY_GATE",
    "LABEL_PARTIAL",
    "OutcomeFamily",
    "RankingLogEntry",
    "RankingLogOutcome",
    "RankingLogStore",
    "StoredRankingLogEntry",
    "classify_label",
    "outcome_family_from_record",
]
