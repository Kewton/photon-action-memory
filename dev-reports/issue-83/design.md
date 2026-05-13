# Design Note — Issue #83: /v1/summarize event-to-summary pipeline

## Objective

Wire the existing `ActionChunker` → `ActionSummaryBuilder` → `SummaryStore`
components together behind `POST /v1/summarize`, which is currently a stub
returning HTTP 501.

After this change:

- A caller can `POST /v1/events` to ingest raw events, then `POST /v1/summarize`
  to build chunk-level `ActionSummary` records from those events and persist them
  to the local `SummaryStore`.
- `POST /v1/context/pack` (no `candidate_summary_ids`, repo-based search) will
  return those summaries on the very next call.
- Re-running `/v1/summarize` over the same event set must not produce duplicate
  rows in `SummaryStore`.

## Scope

Wiring only — no behavioural changes to the underlying components. The
deterministic ID logic already lives inside `ActionChunker` and
`ActionSummaryBuilder`; we rely on it for idempotency.

## Request / Response schemas

Add two new models to `photon_action_memory/api/schema_v2.py`:

```python
class SummarizeRequest(SidecarModel):
    schema_version: SchemaVersionV2
    request_id: str
    session_id: str | None = None      # filter EventStore.list_events
    repo_id: str | None = None         # filter EventStore.list_events
    task_signature: str | None = None  # stamped onto created summaries

class SummarizeResponse(SidecarModel):
    schema_version: SchemaVersionV2
    request_id: str
    status: str                        # "ok"
    chunks_built: int = Field(default=0, ge=0)
    summaries_upserted: int = Field(default=0, ge=0)
    summary_ids: list[str] = Field(default_factory=list)
```

`session_id` / `repo_id` filters mirror `EventStore.list_events(...)`. When
both are `None`, the pipeline summarises every event in the store — useful for
tests and local exploration.

`task_signature`, when provided, is stamped onto every created summary via
`ActionSummary.task_signature` (already in the v0.2 schema). This lets later
context-pack search by task_signature find the summaries.

## Pipeline

In `photon_action_memory/api/server.py` replace `summarize_stub` with:

1. Read events via `event_store.list_events(session_id=..., repo_id=...)`.
2. Pass the list through `ActionChunker().chunk(events)`.
3. For each chunk, build a summary with `ActionSummaryBuilder().build(chunk)`.
4. If `task_signature` was supplied, attach it to the summary via
   `model_copy(update={"task_signature": ...})`.
5. Run each summary through `SummaryCanonicalizer().canonicalize(...)` to keep
   the same grounding invariants the existing upsert path enforces.
6. `_summary_store.upsert(summary)` for each canonicalized summary.
7. Return a `SummarizeResponse` with the list of `summary_id`s.

Errors during the loop are caught and surfaced as HTTP 500 with the original
exception text, consistent with `upsert_summary`.

## Idempotency

The chain `(event_ids) → chunk_id → summary_id` is deterministic:

- `_deterministic_chunk_id(event_ids)` hashes sorted event IDs (chunks.py:96).
- `_deterministic_summary_id(chunk_id)` hashes the chunk_id (summaries.py:31).
- `SummaryStore.upsert` is keyed on `summary_id` with `ON CONFLICT ... DO UPDATE`.

Therefore re-running `/v1/summarize` over the same `(session_id, turn_id)`
events produces the same `summary_id`s and the same row count in the store.
Verified by a focused test.

## Test plan

In `tests/test_sidecar_api.py`:

- Replace `test_summarize_is_m2_stub` with `test_summarize_returns_ok_for_empty_store`
  (200 + zero summaries).
- Add `test_summarize_builds_and_persists_summary` — ingest events, summarise,
  assert `SummaryStore.count() == chunks_built` and that the returned
  `summary_ids` resolve in `SummaryStore.get()`.
- Add `test_summarize_then_context_pack_returns_summary` — summarise, then call
  `/v1/context/pack` for the same `repo_id` (no candidate IDs) and assert the
  generated summary appears in `context_pack.items`.
- Add `test_summarize_is_idempotent` — call `/v1/summarize` twice; assert
  `SummaryStore.count()` does not grow on the second call.
- Add `test_summarize_filters_by_session_id` — two sessions, only one is
  summarised when `session_id` is set.

## Non-goals

- No turn-level vs session-level rollup logic; we keep `summary_level="chunk"`
  as `ActionSummaryBuilder` already does.
- No incremental updates via `SummaryStateUpdater`; that lives in summaries.py
  for future M3 work and is out of scope here.
- No new client wrapper in `api/client.py`.

## Safety Notes

- The endpoint reads only from local stores (event_store, summary_store) created
  by `create_app`. No network calls, no LLM.
- Errors are caught and returned as HTTP 500 rather than letting the FastAPI
  default handler leak internal traces.
