# Issue #68 — Implementation Summary

## New files

| File | Description |
|---|---|
| `photon_action_memory/memory/summary_store.py` | `SummaryStore` — SQLite upsert/get/resolve/search for `ActionSummary` |
| `photon_action_memory/memory/retrieval.py` | `SummaryRetriever` — staleness-filtered retrieval wrapping `SummaryStore` |
| `tests/test_summary_store.py` | 18 unit tests for store and retriever |
| `workspace/anvil/summary.md` | Design reference for Anvil integration |

## Modified files

| File | Change |
|---|---|
| `photon_action_memory/api/server.py` | Added `SummaryUpsertRequest/Response`, `default_summary_store_path()`, `create_app(summary_store=)`, `POST /v1/summary/upsert`, updated `POST /v1/context/pack` to resolve from store |
| `tests/test_context_pack.py` | Updated `test_context_pack_api_degraded_when_summary_ids_given` → `test_context_pack_api_ok_when_unknown_summary_ids_given`; added 3 new API integration tests |

## Acceptance criteria checklist

- [x] `ActionSummary` を SQLite に upsert できる → `SummaryStore.upsert` + `POST /v1/summary/upsert`
- [x] `candidate_summary_ids` から summary を解決できる → `SummaryRetriever.resolve_candidates` wired into `/v1/context/pack`
- [x] repo/task 条件で bounded search できる → `SummaryStore.search(repo_id, task_signature, limit)`
- [x] stale/contradicted summary は ContextPack items に入らない → `SummaryRetriever._filter_stale` + `ContextAdmissionController`
- [x] ungrounded facts は除外または partial → `SummaryCanonicalizer` (existing) + `SummaryFidelityChecker` (existing)
- [x] `/v1/context/pack` が resolved summaries から summary-only ContextPack を返せる → verified by `test_context_pack_api_resolves_stored_summaries`
