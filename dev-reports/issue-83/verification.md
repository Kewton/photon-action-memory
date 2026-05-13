# Verification — Issue #83

## Commands

### Focused: /v1/summarize tests

```
$ python -m pytest tests/test_sidecar_api.py -x -q
..........
10 passed in 0.32s
```

The 10 tests include the 5 new `test_summarize_*` cases plus the existing
health/events/suggest/evaluate/client tests, which all continue to pass.

### Adjacent: chunks, summaries, summary store, context pack, schema v2

```
$ python -m pytest tests/test_chunks.py tests/test_summaries.py \
    tests/test_summary_store.py tests/test_anvil_context_pack_api.py \
    tests/test_context_pack.py tests/test_schema_v2.py -x -q
...
252 passed in 0.64s
```

No regressions in the modules whose contracts the new endpoint touches.

### Full suite

```
$ python -m pytest -x -q
...
798 passed, 1 skipped in 2.53s
```

Single skip is the opt-in MLX smoke (`tests/integration/test_mlx_smoke.py`),
unrelated to this change.

### Lint

```
$ python -m ruff check photon_action_memory/api/server.py \
    photon_action_memory/api/schema_v2.py tests/test_sidecar_api.py
All checks passed!
```

### Type check (strict)

```
$ python -m mypy photon_action_memory
Success: no issues found in 49 source files
```

## Acceptance criteria evidence

- **200 on valid request** — see `test_summarize_returns_ok_for_empty_store`
  and `test_summarize_builds_and_persists_summary`.
- **Events → ActionChunk → ActionSummary** — the build/persist test asserts
  `chunks_built == 1`, `summaries_upserted == 1`, and a non-empty
  `actions_done` carrying the original `evt-sum-a` evidence id.
- **Stored in SummaryStore** — `summary_store.count() == 1` and
  `summary_store.get(summary_id)` returns the same summary.
- **Retrievable via /v1/context/pack** — the post-summarize context pack
  contains the freshly-generated `summary_id` in `context_pack.items`.
- **Idempotent re-runs** — second call returns the identical `summary_ids`
  list and does not grow `summary_store.count()`.
- **Existing tests intact** — full suite passes (798/1 skipped).
