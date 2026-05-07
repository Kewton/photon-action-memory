# Verification — Issue #70

## Test run results

### Targeted test
```
pytest tests/test_anvil_contract.py -v
# 16 passed
```

### All new Anvil test files
```
pytest tests/test_anvil_contract.py tests/test_anvil_context_pack_api.py \
       tests/test_anvil_evaluate.py tests/test_anvil_evidence_expand.py \
       tests/test_anvil_feedback_scoring.py -v
# 58 passed
```

### Full suite (regression check)
```
pytest tests/ -q
# 713 passed, 1 skipped (MLX smoke opt-in)
# was 655 passed before this issue
```

## Acceptance criteria

| Criterion | Status | Evidence |
|---|---|---|
| `pytest tests/test_anvil_contract.py` 相当が通る | PASS | 16/16 passed |
| Anvil shared fixtures validate against photon schema/API | PASS | `test_anvil_evaluate_shadow_fixture_validates`, `test_anvil_adoption_log_fixture_validates_all_statuses`, etc. |
| unsafe raw log fixture is not prompt-visible | PASS | `test_anvil_raw_log_fixture_not_in_context_pack_items`, `test_anvil_raw_evidence_all_denied`, `test_anvil_raw_evidence_deny_decisions_have_policy` |
| shadow/canary evaluate fixtures can be stored and aggregated | PASS | `test_anvil_shadow_evaluate_fixture_stored_in_event_store`, `test_anvil_shadow_evaluate_multiple_fixtures_aggregate`, `test_anvil_shadow_evaluate_log_aggregates_correctly` |
| evidence expansion safety profile returns no raw output | PASS | `test_anvil_profile_denies_stdout_with_allow_raw_true`, `test_api_anvil_profile_denies_stdout`, all `anvil_profile` tests |
| 既存 test suite が regression しない | PASS | Full suite: 713 passed (no regressions) |
