# Anvil Summary Store — Design Note (Issue #68)

## Problem

`/v1/context/pack` previously returned a `summary_store_unavailable` warning
whenever `candidate_summary_ids` were given, because no SQLite summary store
existed.  `ActionSummary` objects built from Anvil execution history had
nowhere to persist between sessions.

## Solution

### New modules

| Module | Responsibility |
|---|---|
| `photon_action_memory/memory/summary_store.py` | SQLite CRUD for `ActionSummary` (upsert / get / resolve / search) |
| `photon_action_memory/memory/retrieval.py` | Retrieval with staleness guard pre-filtering |

### New endpoint

`POST /v1/summary/upsert` — Anvil pushes an `ActionSummary` into the store
after completing an action chunk.  Response: `{ summary_id, status }`.

### Updated endpoint

`POST /v1/context/pack` — resolves `candidate_summary_ids` from the store via
`SummaryRetriever`, then passes the result to `build_context_pack`.  Unknown
IDs are silently skipped (no warning).

## Staleness guarantee

`SummaryRetriever._filter_stale` drops summaries whose `validity.status` is
`stale` or `contradicted` before they reach `ContextAdmissionController`,
which provides a second layer of the same check.

When a `StalenessContext` is provided (commit hash, refuted claims, …)
`StalenessGuard.apply` updates each summary's validity dynamically so that
context-aware signals are honoured even when the stored validity is `valid`.

## SQLite schema

```sql
CREATE TABLE action_summaries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    summary_id      TEXT NOT NULL UNIQUE,
    repo_id         TEXT,
    task_signature  TEXT,
    validity_status TEXT NOT NULL DEFAULT 'valid',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    payload_json    TEXT NOT NULL
);
```

Indexes on `repo_id`, `task_signature`, and `validity_status` support
bounded search by repo and task.

## Default paths

| Variable | Default |
|---|---|
| `PHOTON_ACTION_MEMORY_DB` | `$TMPDIR/photon-action-memory/events.sqlite` |
| `PHOTON_ACTION_MEMORY_SUMMARY_DB` | `$TMPDIR/photon-action-memory/summaries.sqlite` |
