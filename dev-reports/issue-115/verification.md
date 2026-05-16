# Issue #115 — verification

## Focused tests

`python -m pytest tests/test_evaluate.py tests/test_summary_feedback.py -x -q`

- Result: **67 passed in 0.45s**
- Covers:
  - The two new Issue #115 regression tests
  - All existing /v1/evaluate endpoint and contract tests
  - The summary feedback aggregation flow that consumes
    `summary_ids_adopted`

## Full suite (schema is a shared contract)

`python -m pytest -x -q`

- Result: **998 passed, 1 skipped in 17.93s**
- 1 skip is the opt-in MLX smoke test
  (`tests/integration/test_mlx_smoke.py`), unrelated to this change.

## Acceptance criteria mapping

| Criterion | Verified by |
| --- | --- |
| `ContextPackEvalEvent.summary_ids_adopted: list[str]` (default empty) | Pre-existing; covered by `test_evaluate_legacy_anvil_omits_summary_ids_fields` (defaults to `[]`). |
| `ContextPackEvalEvent.summary_ids_adopted_truncated: bool` (default False) | `schema_v2.py` change + `test_evaluate_legacy_anvil_omits_summary_ids_fields` (defaults to `False`). |
| `server.py::evaluate` payload includes both fields | `server.py` change + `test_evaluate_persists_summary_ids_adopted_fields` (asserts stored payload). |
| Events table JSON contains `summary_ids_adopted` | `test_evaluate_persists_summary_ids_adopted_fields` reads via `store.list_events()[0].payload`. |
| Regression test in `test_evaluate.py` | Two new tests added; previously zero coverage. |
| Backward compatibility for legacy Anvil (no summary fields) | `test_evaluate_legacy_anvil_omits_summary_ids_fields`. |
