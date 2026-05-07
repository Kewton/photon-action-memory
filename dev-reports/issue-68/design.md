# Issue #68 — Design Note

## Objective

Implement a persistent `ActionSummary` store so that Anvil execution history
can be accumulated and surfaced via `/v1/context/pack`.

## Approach

Two new modules sit below the existing `context/pack.py` pipeline:

```
SummaryStore (SQLite)
    ↑ upsert  ↓ resolve / search
SummaryRetriever (staleness filter)
    ↓ list[ActionSummary]
build_context_pack → ContextAdmissionController → ContextPack
```

**`SummaryStore`** — thin SQLite wrapper.  `upsert` uses
`ON CONFLICT(summary_id) DO UPDATE` so Anvil can push updates without
checking existence first.  `resolve(ids)` preserves input order.
`search(repo_id, task_signature, limit)` gives bounded retrieval by task
context.

**`SummaryRetriever`** — wraps `SummaryStore` and filters out stale /
contradicted summaries before they reach the admission pipeline.
Accepts an optional `StalenessContext` so context-aware signals (commit
change, refuted claims) are evaluated at retrieval time.

**`/v1/summary/upsert`** — new HTTP endpoint for Anvil to push an
`ActionSummary` into the store.

**`/v1/context/pack`** — now resolves `candidate_summary_ids` from the store
(instead of returning a `summary_store_unavailable` warning).  Stale /
contradicted summaries are pre-filtered by `SummaryRetriever`; the
`ContextAdmissionController` provides a second guard layer.

## Key invariants

1. Stale or contradicted summaries never appear in `ContextPack.items`.
2. Ungrounded facts are excluded by `SummaryCanonicalizer` at build time and
   by `SummaryFidelityChecker` at validate time.
3. `created_at` is set once and never overwritten on upsert.
4. Unknown `candidate_summary_ids` are silently skipped (no warning).
