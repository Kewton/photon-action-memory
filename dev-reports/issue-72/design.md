# Design Note — Issue #72: C2 Rollout Policy

## Problem

The Anvil ↔ photon-action-memory integration has been running in shadow mode
(context pack built, never injected). Before promoting to canary (live injection
for a fraction of sessions), three safety gates must be verified:

1. **Turn count** — shadow data must cover enough turns to be statistically meaningful.
2. **Raw tool token cleanliness** — no raw stdout/stderr may appear in the injected prompt.
3. **Sidecar stability** — error/timeout rate must be below an acceptable threshold.

There was no code or documentation formalizing these gates.

## Approach

### `context/canary.py` — eligibility predicate

Add `CanaryRolloutPolicy` (Pydantic model with `min_turns_for_canary` and
`max_fail_open_rate`) and `is_canary_eligible(turn_count, raw_tool_tokens,
fail_open_rate, policy)` returning `(bool, reason)`.

This is a pure predicate: no side effects, no I/O. Placed in `context/canary.py`
alongside the existing canary admission logic.

### `eval/metrics.py` — rollout metrics aggregation

Add `RolloutMetrics` (Pydantic model) and `build_rollout_metrics(eval_records,
*, raw_tool_tokens_in_prompt, min_turns_for_canary, max_fail_open_rate)`.

The function wraps `aggregate_context_pack_eval` (from `eval/context_pack_log`)
and delegates the eligibility check to `is_canary_eligible`. It produces a
single `RolloutMetrics` object with `canary_eligible`, `rollback_triggered`, and
human-readable reasons.

`raw_tool_tokens_in_prompt` is passed in by the caller (from `PollutionReport`)
rather than recomputing it inside `build_rollout_metrics`. This keeps
`build_rollout_metrics` focused and testable with synthetic values.

### Fixture + tests

- `tests/fixtures/v0.2/rollout_metrics_fixture.json` — four named scenarios
  exercising each gate and the rollback path.
- `tests/test_rollout_policy.py` — 14 tests: 8 unit tests for
  `is_canary_eligible` and 6 fixture-driven tests for `build_rollout_metrics`.

### Docs

- `workspace/anvil/rollout_policy.md` — full checklist, rollback conditions,
  and API usage examples.
- `workspace/anvil/summary.md` — quick-reference section appended.

## Alternatives considered

- **Separate `eval/rollout.py` module**: rejected to keep the change minimal;
  `RolloutMetrics` fits naturally alongside `MetricsReport` in `metrics.py`.
- **`is_canary_eligible` inline in `build_rollout_metrics`**: rejected to avoid
  duplicating logic; the predicate belongs in `context/canary.py` where the
  canary policy lives.
