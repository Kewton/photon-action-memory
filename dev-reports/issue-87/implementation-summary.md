# Issue #87 — Implementation Summary

## Files changed

| File | Change |
|---|---|
| `photon_action_memory/api/schema_v2.py` | Added typed `summary_ids_adopted: list[str]` to `ContextPackEvalEvent`. |
| `photon_action_memory/eval/summary_feedback.py` | New module: `SummaryFeedbackRecord`, `confidence()`, `is_disabled()`, `classify_outcome()`, `is_adopted()`. |
| `photon_action_memory/memory/summary_store.py` | Added `summary_feedback` table, `record_outcomes()`, `get_feedback()`, `get_feedback_map()`. |
| `photon_action_memory/context/pack.py` | `build_context_pack(..., summary_feedback=…)` filters disabled summaries and stably reorders by confidence. |
| `photon_action_memory/api/server.py` | `/v1/evaluate` calls `record_outcomes`; `/v1/context/pack` loads `get_feedback_map` and passes it into the builder. |
| `tests/test_summary_feedback.py` | New test file: 32 tests covering helpers, store, pack admission, and end-to-end flow. |

## Behaviour

### `/v1/evaluate`

Agents can now attach `summary_ids_adopted: ["sum-…", "sum-…"]` to the
`context_pack_event` payload. On each call the sidecar increments per-summary
counters in the `summary_feedback` table:

- `quality_turns` — total non-excluded turns where the summary appeared.
- `adoption_count` — turns where `adoption_status ∈ {adopted, partial}`.
- `success_count` / `failure_count` / `safety_violation_count` — partitioned by
  outcome.
- `expand_request_count` — turns where `evidence_expand_requested=True`.

Excluded statuses (`error`, `not_available`, `shadow_not_injected`) are no-ops:
infrastructure errors never pollute the per-summary signal. Missing
`summary_ids_adopted` (legacy callers) is also a no-op.

### `/v1/context/pack`

After resolving the candidate summaries, the server reads their feedback rows
and passes the map into `build_context_pack`. The builder:

1. **Disables** summaries with `safety_violation_count >= 1` or
   (`adoption_count >= 3` AND Laplace-smoothed confidence `< 0.34`).
   Disabled summaries are emitted as `omitted` items with a "disabled by
   feedback" reason and a `deny` admission decision.
2. **Reorders** remaining summaries by descending confidence (stable on ties).
   Under a tight token budget, the higher-confidence summary admits first.
3. **Falls through** when no feedback is supplied or no rows exist: the
   admission pipeline is identical to the pre-#87 baseline (deterministic
   fallback).

### Confidence model

`confidence = (success + 1) / (success + failure + 2)` — Laplace smoothing with
a neutral 0.5 prior. A single failure does not pin the score to zero, but
repeated failures rapidly converge below the 0.34 disable threshold.

## Aggregate-safety

The `summary_feedback` table only stores counters and a timestamp. No raw
prompt text, tool output, user request, or evidence content is persisted; the
table is safe for future model training feature extraction under the same
contract as `PackFeedback`.

## Acceptance criteria coverage

| Criterion | Where |
|---|---|
| summary_id 単位の採用/成功/失敗/safety 集計 | `SummaryStore.record_outcomes` + `summary_feedback` table |
| 悪化 summary を低 confidence / disabled として扱える | `is_disabled` + `build_context_pack` deny path |
| 有効 summary を優先できる | `_apply_feedback` confidence sort under budget |
| feedback がなくても deterministic fallback | `_apply_feedback` short-circuits on `None` / empty dict |
