# Implementation Summary — Issue #83

## What changed

Replaced the `POST /v1/summarize` HTTP 501 stub with a working pipeline that
ingests events from the local `EventStore`, runs them through the existing
`ActionChunker` and `ActionSummaryBuilder`, canonicalizes the resulting
summaries, and persists them to `SummaryStore`.

### `photon_action_memory/api/schema_v2.py`

- Added `SummarizeRequest` (`schema_version`, `request_id`, optional
  `session_id`, `repo_id`, `task_signature`).
- Added `SummarizeResponse` (`status`, `chunks_built`, `summaries_upserted`,
  `summary_ids`).
- Exported both via `__all__`.

### `photon_action_memory/api/server.py`

- Imported the new request/response models, plus `ActionChunker`,
  `ActionSummaryBuilder`, and `SummaryCanonicalizer`.
- Replaced `summarize_stub` with the `/v1/summarize` handler:
  - Filters events by `session_id` / `repo_id` via `event_store.list_events`.
  - Builds chunks with `ActionChunker().chunk(...)`.
  - For each chunk: builds an `ActionSummary`, attaches `task_signature` if
    supplied, canonicalizes it, and upserts to `SummaryStore`.
  - Wraps the loop in `try/except` and returns HTTP 500 on failure
    (mirrors `/v1/summary/upsert`).
  - Returns a `SummarizeResponse` with the deterministic `summary_id` list.

### `tests/test_sidecar_api.py`

- Removed `test_summarize_is_m2_stub` (the 501 contract is gone).
- Added five focused tests:
  - `test_summarize_returns_ok_for_empty_store` — 200, zero chunks.
  - `test_summarize_builds_and_persists_summary` — generates a summary and
    persists it; `task_signature` is preserved.
  - `test_summarize_then_context_pack_returns_summary` — the generated
    `summary_id` shows up in the next `/v1/context/pack` items.
  - `test_summarize_is_idempotent_across_repeat_calls` — re-running over the
    same event set returns the same `summary_ids` and does not grow
    `SummaryStore.count()`.
  - `test_summarize_filters_by_session_id` — `session_id` filter is honored
    end-to-end.

## Acceptance Criteria checklist

| Criterion | Status |
|---|---|
| `/v1/summarize` returns 200 for a valid request | ✅ covered by `test_summarize_returns_ok_for_empty_store` and the build/persist test |
| Raw events → `ActionChunk` and `ActionSummary` are generated | ✅ `test_summarize_builds_and_persists_summary` |
| Generated summary is stored in `SummaryStore` | ✅ `summary_store.count() == 1` and `summary_store.get(id)` returns the summary |
| Following `/v1/context/pack` retrieves the saved summary | ✅ `test_summarize_then_context_pack_returns_summary` |
| Re-running over same event set does not duplicate summaries | ✅ `test_summarize_is_idempotent_across_repeat_calls` |
| Existing tests still pass | ✅ 798 passed, 1 skipped |

## Idempotency mechanism

`ActionChunker` produces a SHA-256 chunk_id from sorted event IDs, and
`ActionSummaryBuilder` derives a SHA-256 summary_id from the chunk_id. The
`SummaryStore.upsert` SQL uses `ON CONFLICT(summary_id) DO UPDATE`, so the same
event set yields the same row across repeated calls.

## Files touched

- `photon_action_memory/api/schema_v2.py`
- `photon_action_memory/api/server.py`
- `tests/test_sidecar_api.py`
- `dev-reports/issue-83/design.md` (new)
- `dev-reports/issue-83/implementation-summary.md` (new)
- `dev-reports/issue-83/verification.md` (new)
