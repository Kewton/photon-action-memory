# Implementation Summary — Issue #72

## Files changed

### `photon_action_memory/context/canary.py`
- Added `CanaryRolloutPolicy` — Pydantic model with `min_turns_for_canary: int = 10`
  and `max_fail_open_rate: float = 0.05`.
- Added `CANARY_ROLLOUT_POLICY` default instance.
- Added `is_canary_eligible(turn_count, raw_tool_tokens_in_prompt, *, fail_open_incident_rate, policy)
  → tuple[bool, str]` — checks gates in order: turn count → raw tokens → fail-open rate.
- Updated `__all__`.

### `photon_action_memory/eval/metrics.py`
- Added top-level imports: `CanaryRolloutPolicy`, `is_canary_eligible` from
  `context.canary`; `RawContextPackEvalRecord`, `aggregate_context_pack_eval` from
  `eval.context_pack_log`.
- Added `ROLLOUT_METRICS_SCHEMA = "rollout-metrics.v1"`.
- Added `RolloutMetrics` Pydantic model: `total_turns`, `raw_tool_tokens_in_prompt`,
  `adoption_rate`, `fail_open_incident_rate`, `canary_eligible`, `ineligible_reason`,
  `rollback_triggered`, `rollback_reason`.
- Added `build_rollout_metrics(eval_records, *, raw_tool_tokens_in_prompt, min_turns_for_canary, max_fail_open_rate) → RolloutMetrics`.
- Updated `__all__`.

## Files created

### `tests/fixtures/v0.2/rollout_metrics_fixture.json`
Four scenarios: `canary_ready`, `too_few_turns`, `raw_tool_leak`, `high_fail_open`.

### `tests/test_rollout_policy.py`
14 tests: 8 unit tests for `is_canary_eligible`, 6 fixture-driven tests for
`build_rollout_metrics` (including schema version and empty-records edge case).

### `workspace/anvil/rollout_policy.md`
Full shadow → canary promotion checklist, rollback conditions, API usage examples,
and fixture scenario table.

## Files updated

### `workspace/anvil/summary.md`
Added "Rollout Policy" section with quick-reference gate table and module index.

## Acceptance criteria mapping

| Criterion | Satisfied by |
|---|---|
| shadow/canary rollout checklist が docs 化 | `workspace/anvil/rollout_policy.md` |
| Anvil evaluate fixture から rollout metrics を生成 | `build_rollout_metrics` + `rollout_metrics_fixture.json` |
| turn 未満は canary 不可として判定 | `is_canary_eligible` turn-count gate, `too_few_turns` fixture test |
| raw tool tokens in prompt が 0 であることを確認 | gate 2 in `is_canary_eligible`, `raw_tool_leak` fixture test |
| rollback 条件を fixture test で検証 | `test_rollout_metrics_raw_tool_leak_triggers_rollback`, `test_rollout_metrics_high_fail_open_triggers_rollback` |
