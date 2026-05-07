# Verification — Issue #67

## Focused Tests

```
python -m pytest tests/test_evaluate.py tests/test_schema_v2.py -v
```

Result: **89 passed**

New tests:
- `test_evaluate_request_validates_shadow_not_injected` ✓
- `test_evaluate_request_validates_not_available` ✓
- `test_evaluate_request_validates_error_status` ✓
- `test_anvil_shadow_fixture_returns_logged_one` ✓
- `test_evaluate_payload_excludes_raw_stdout_stderr` ✓
- `test_aggregate_counts_shadow_not_injected_not_available_error` ✓
- `test_evaluate_malformed_empty_request_id_returns_degraded` ✓

## Full Suite

```
python -m pytest --tb=short -q
```

Result: **623 passed, 1 skipped** (MLX opt-in skip is pre-existing, hardware-gated)

No regressions introduced.
