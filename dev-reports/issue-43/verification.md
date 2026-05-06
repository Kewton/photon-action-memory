# Issue #43 — Verification Report

## Tool run results

### ruff format
```
69 files left unchanged
```
No reformatting needed after final pass.

### ruff check
```
All checks passed!
```

### mypy
```
Success: no issues found in 67 source files
```
Checked `photon_action_memory/` (all modules) and `tests/` (all test files).

### pytest
```
536 passed, 1 skipped in 1.27s
```
The skipped test is `tests/integration/test_mlx_smoke.py` — opt-in only, unchanged.

---

## New tests: 27 total (26 in `test_evaluate.py` + 1 updated in `test_sidecar_api.py`)

| Test | Result |
|---|---|
| `test_evaluate_adopted_context_pack_returns_logged_one` | PASS |
| `test_evaluate_ignored_context_pack_returns_logged_one` | PASS |
| `test_evaluate_no_context_pack_event_returns_logged_zero` | PASS |
| `test_evaluate_logs_event_to_store` | PASS |
| `test_evaluate_with_evidence_expand_fields` | PASS |
| `test_evaluate_request_schema_round_trip` | PASS |
| `test_evaluate_response_schema_round_trip` | PASS |
| `test_evaluate_adopted_fixture_validates` | PASS |
| `test_evaluate_ignored_fixture_validates` | PASS |
| `test_adoption_log_fixture_records_validate` | PASS |
| `test_aggregate_empty_records_returns_zero_report` | PASS |
| `test_aggregate_all_adopted` | PASS |
| `test_aggregate_mixed_adoption_and_outcomes` | PASS |
| `test_aggregate_from_fixture_file` | PASS |
| `test_valid_complete_sequence` | PASS |
| `test_valid_sequence_with_evidence_expand` | PASS |
| `test_missing_context_pack_step_is_violation` | PASS |
| `test_missing_evaluate_step_is_violation` | PASS |
| `test_wrong_order_is_violation` | PASS |
| `test_evidence_expand_without_context_pack_is_violation` | PASS |
| `test_empty_sequence_has_violations` | PASS |
| `test_contract_has_all_required_steps` | PASS |
| `test_contract_has_optional_steps` | PASS |
| `test_contract_invariants_are_non_empty` | PASS |
| `test_required_steps_are_marked_required` | PASS |
| `test_contract_steps_have_endpoints` | PASS |
| `test_evaluate_returns_ok_for_valid_request` (sidecar_api) | PASS |

---

## Changed files summary

| File | Change |
|---|---|
| `photon_action_memory/api/schema_v2.py` | Added `ContextPackAdoptionStatus`, `ContextPackEvalEvent`, `EvaluateRequest`, `EvaluateResponse` |
| `photon_action_memory/api/server.py` | Replaced 501 evaluate stub with working endpoint; imports updated |
| `photon_action_memory/eval/context_pack_log.py` | New: `ContextPackEvalRecord`, `ContextPackAdoptionReport`, `aggregate_context_pack_eval` |
| `photon_action_memory/integration/__init__.py` | New: package init |
| `photon_action_memory/integration/context_pack_contract.py` | New: `IntegrationContract`, `CONTEXT_PACK_CONTRACT`, `validate_call_sequence` |
| `tests/fixtures/v0.2/evaluate_context_pack_adopted.json` | New fixture |
| `tests/fixtures/v0.2/evaluate_context_pack_ignored.json` | New fixture |
| `tests/fixtures/v0.2/context_pack_adoption_log.json` | New multi-turn fixture |
| `tests/test_evaluate.py` | New: 26 tests |
| `tests/test_sidecar_api.py` | Updated: split stub test, added evaluate 200 test |

---

## Regression check

No previously passing tests were broken.  The only pre-existing test that touched
`/v1/evaluate` (`test_summarize_and_evaluate_are_m2_stubs`) was split:
- `test_summarize_is_m2_stub` — unchanged, still expects 501
- `test_evaluate_returns_ok_for_valid_request` — new assertion against the live endpoint
