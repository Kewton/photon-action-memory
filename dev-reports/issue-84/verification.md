# Verification — Issue #84

## Commands run

```
python -m pytest tests/test_summarize_endpoint.py tests/test_sidecar_api.py -x -q
python -m pytest tests/test_context_pack.py tests/test_schema_v2.py tests/test_summaries.py \
    tests/test_summary_store.py tests/test_summary_fidelity.py \
    tests/test_sidecar_api.py tests/test_summarize_endpoint.py -x -q
python -m pytest tests/ -x -q --ignore=tests/integration
python -m ruff check photon_action_memory/api/server.py photon_action_memory/api/schema_v2.py \
    tests/test_summarize_endpoint.py tests/test_sidecar_api.py
python -m ruff format --check photon_action_memory/api/server.py photon_action_memory/api/schema_v2.py \
    tests/test_summarize_endpoint.py tests/test_sidecar_api.py
python -m mypy photon_action_memory/api/server.py photon_action_memory/api/schema_v2.py
```

## Results

| Step | Outcome |
| --- | --- |
| Focused: summarize + sidecar tests | **13 passed** |
| Broader: schema_v2 / summaries / context_pack / fidelity / sidecar | **233 passed** |
| Full unit suite (excluding `tests/integration/`) | **801 passed** |
| ruff check on touched files | **all checks passed** |
| ruff format on touched files | clean after one auto-format pass on `server.py` |
| mypy on touched files | **Success: no issues found in 2 source files** |

## What the tests demonstrate

- `test_summarize_persists_at_requested_level[turn|session|case]` (parametrized)
  posts inline `ActionChunks`, asserts the response contains a summary at the
  requested level, then re-reads the summary from `SummaryStore` and checks
  `token_cost.tokens_saved_vs_raw` matches the response field.
- `test_summarize_requires_at_least_one_chunk` confirms the fail-open path:
  HTTP 200, `sidecar_status="degraded"`, warning `summarize_input`.
- `test_context_pack_retrieves_session_level_summary` summarizes at
  `summary_level="session"` with a `task_signature`, then posts to
  `/v1/context/pack` with the same `task_signature`; the resulting pack
  contains the stored summary (`mode="summary_only"`) and its
  `token_budget.tokens_saved_vs_raw > 0`.
- `test_context_pack_omits_raw_evidence_after_summarize` shows that raw
  evidence in the pack request never reaches `items`; it is recorded in
  `omitted` instead.
- `test_summarize_overrides_summary_level_when_built_at_chunk` locks in that
  the request's `summary_level` overrides `ActionSummaryBuilder`'s default
  `"chunk"`.

## Non-regressions

- All 801 pre-existing unit tests continue to pass (no integration tests
  were modified).
- `/v1/summary/upsert`, `/v1/context/pack`, `/v1/evidence/expand`,
  `/v1/summary/validate`, `/v1/evaluate`, and `/v1/suggest` are unchanged.

## Outstanding follow-ups

- No blockers. A future PR can extend `/v1/summarize` to accept `chunk_ids`
  once an `ActionChunk` store lands; the request schema already includes a
  forward-compatible `policy` block.
