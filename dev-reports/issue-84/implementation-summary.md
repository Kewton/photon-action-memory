# Implementation Summary — Issue #84

## What changed

`/v1/summarize` was a 501 stub; it is now a real endpoint that folds
ActionChunks into a hierarchical ActionSummary at the requested
`summary_level` (`turn`/`session`/`case`/`chunk`), persists it via
`SummaryStore`, and surfaces `tokens_saved_vs_raw` on both the response and
the stored summary. `/v1/context/pack` already retrieves by `repo_id` /
`task_signature`, so the wiring becomes end-to-end without changes to the
pack route.

## Files modified

- `photon_action_memory/api/schema_v2.py`
  - Added `SummarizePolicy`, `SummarizeRequest`, `SummarizeResponse`.
  - Updated `__all__`.
- `photon_action_memory/api/server.py`
  - Replaced `summarize_stub` (501) with `summarize` route.
  - New helpers: `_tokens_saved`, `_build_hierarchical_summary`.
  - Imports `ActionChunk`, `SummarizeRequest`, `SummarizeResponse`,
    `TokenCost`, and `ActionSummaryBuilder` / `SummaryCanonicalizer` /
    `SummaryStateUpdater`.
- `tests/test_sidecar_api.py`
  - Replaced `test_summarize_is_m2_stub` with
    `test_summarize_rejects_empty_request_with_degraded_status` to lock in
    fail-open semantics on empty chunks.

## Files added

- `tests/test_summarize_endpoint.py` — 7 new tests covering:
  - Persistence at `summary_level` = `turn`, `session`, `case`.
  - Empty-chunks fail-open (`sidecar_status="degraded"`, warning surfaced).
  - End-to-end summarize → context-pack retrieval via `task_signature`.
  - Raw evidence stays omitted; prompt-visible items remain summary-only.
  - `summary_level` override above the builder's default `"chunk"`.
- `dev-reports/issue-84/design.md`
- `dev-reports/issue-84/implementation-summary.md` (this file).
- `dev-reports/issue-84/verification.md`

## Behavior notes

- The new endpoint runs `SummaryFidelityChecker` against the local event
  store so the response carries a `SummaryValidationResult` alongside the
  summary.
- Hierarchical folding reuses `ActionSummaryBuilder` and
  `SummaryStateUpdater`, then overrides
  `summary_level`/`session_id`/`repo_id`/`task_signature`/`summary_id` from
  the request so retrieval metadata matches what the caller asked for.
- Errors during fidelity check or persistence degrade `sidecar_status` to
  `"degraded"` and append a warning — they never raise a 5xx, consistent
  with the existing fail-open style of `/v1/context/pack`.

## Acceptance criteria coverage

| AC | Status | Evidence |
| --- | --- | --- |
| `/v1/summarize` persists summaries at `turn`/`session`/`case` | ✅ | `tests/test_summarize_endpoint.py::test_summarize_persists_at_requested_level` (parametrized) |
| `/v1/context/pack` retrieves the summary via repo/task | ✅ | `tests/test_summarize_endpoint.py::test_context_pack_retrieves_session_level_summary` |
| Prompt-visible items are summary-only; raw events stay out | ✅ | `tests/test_summarize_endpoint.py::test_context_pack_omits_raw_evidence_after_summarize` |
| `tokens_saved_vs_raw` observable on response/stored summary | ✅ | `test_summarize_persists_at_requested_level` (stored), `test_context_pack_retrieves_session_level_summary` (pack budget) |

## Out of scope (explicit)

- `chunks` are accepted inline; no chunk-id store is introduced.
- `policy` flags are accepted but advisory in M2.
- No change to `/v1/summary/upsert` (backwards compatible).
- No change to `context/pack.py` or `memory/retrieval.py` — repo/task
  scoping already met the acceptance bar.
