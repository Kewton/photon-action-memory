# Verification — Issue #72

## Test run

```
python -m pytest tests/test_rollout_policy.py -v
```

```
14 passed in 0.06s
```

All 14 tests pass:
- `test_is_canary_eligible_passes_all_gates`
- `test_is_canary_eligible_too_few_turns`
- `test_is_canary_eligible_minimum_turns_boundary`
- `test_is_canary_eligible_raw_tool_tokens_nonzero`
- `test_is_canary_eligible_raw_tool_tokens_zero_passes`
- `test_is_canary_eligible_high_fail_open_rate`
- `test_is_canary_eligible_fail_open_at_threshold_passes`
- `test_is_canary_eligible_turn_check_before_raw_token_check`
- `test_rollout_metrics_canary_ready_fixture`
- `test_rollout_metrics_too_few_turns_ineligible`
- `test_rollout_metrics_raw_tool_leak_triggers_rollback`
- `test_rollout_metrics_high_fail_open_triggers_rollback`
- `test_rollout_metrics_schema_version`
- `test_rollout_metrics_empty_records`

## Regression check

```
python -m pytest tests/ --ignore=tests/integration -q
```

```
770 passed in 1.90s
```

No regressions. The new imports in `eval/metrics.py` (`context.canary` and
`eval.context_pack_log`) introduce no circular dependencies.
