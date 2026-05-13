# Issue #87 — Verification

## Focused tests (new)

```
$ python -m pytest tests/test_summary_feedback.py -q
................................                                         [100%]
32 passed in 0.26s
```

The new file covers:

- Pure helpers — `confidence`, `is_disabled`, `classify_outcome`, `is_adopted`
  including the neutral prior, safety zero-tolerance, and S2-03-style
  repeated-failure disable.
- `SummaryStore.record_outcomes` and `get_feedback`/`get_feedback_map` for
  success / failure / safety / ignored / excluded-status records and empty
  inputs.
- `build_context_pack(..., summary_feedback=…)` — disabled filtering, safety
  filtering, confidence-priority under tight budgets, and the
  no-feedback deterministic fallback.
- End-to-end via `TestClient`: `/v1/evaluate` writes feedback rows and a
  subsequent `/v1/context/pack` omits the disabled summary while admitting the
  good one.

## Regression — full unit suite

```
$ python -m pytest -q --ignore=tests/integration
... 826 passed in 2.17s
```

Including the pre-existing `test_evaluate.py`, `test_summary_store.py`,
`test_context_pack.py`, and `test_anvil_feedback.py` files — all green.

## Lint and types

```
$ python -m ruff check photon_action_memory/ tests/test_summary_feedback.py
All checks passed!

$ python -m mypy photon_action_memory/
Success: no issues found in 50 source files
```

## Integration

```
$ python -m pytest tests/integration -q
1 skipped in 0.02s
```

The single integration test (MLX smoke) is an opt-in macOS workflow and is
unrelated to the touched contracts.

## Shared-contract risk assessment

- `EvaluateRequest` / `ContextPackEvalEvent` gained one optional typed field
  (`summary_ids_adopted: list[str] = []`). Existing agents that omit it
  continue to validate (default empty list). `SidecarModel` keeps
  `extra="allow"`.
- `SummaryStore` adds a new table; existing rows and queries are unchanged.
  `_initialize_schema` is idempotent via `CREATE TABLE IF NOT EXISTS`.
- `build_context_pack` adds a new optional keyword argument; existing callers
  (e.g. `_resolve_context_summaries` test fixtures) continue to work without
  passing it.
