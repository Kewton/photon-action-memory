# Implementation Summary — Issue #67

## Files Modified

| File | Change |
|---|---|
| `photon_action_memory/api/schema_v2.py` | Extended `ContextPackAdoptionStatus` Literal with `shadow_not_injected`, `not_available`, `error` |
| `photon_action_memory/eval/context_pack_log.py` | Added `shadow_not_injected_count`, `not_available_count`, `error_count` to `ContextPackAdoptionReport`; updated `aggregate_context_pack_eval()` |
| `photon_action_memory/api/server.py` | Added malformed-but-parseable detection (empty `context_pack_request_id`); added explicit comment about raw field exclusion policy |
| `tests/test_evaluate.py` | Added 7 new focused tests covering all acceptance criteria |

## Files Created

| File | Purpose |
|---|---|
| `tests/fixtures/v0.2/evaluate_anvil_shadow.json` | Anvil shadow fixture with `shadow_not_injected` for `/v1/evaluate` |
| `tests/fixtures/v0.2/context_pack_adoption_log_anvil.json` | Multi-turn log with Anvil statuses for aggregate tests |

## Acceptance Criteria Coverage

| Criterion | Implementation |
|---|---|
| `EvaluateRequest` validates `shadow_not_injected`, `not_available`, `error` | `ContextPackAdoptionStatus` Literal extended; 3 schema tests |
| Anvil shadow fixture returns `logged=1` | `evaluate_anvil_shadow.json` + `test_anvil_shadow_fixture_returns_logged_one` |
| Evaluate payload excludes raw stdout/stderr | Explicit payload construction + `test_evaluate_payload_excludes_raw_stdout_stderr` |
| Adoption aggregate counts shadow/error/not_available | `ContextPackAdoptionReport` + `test_aggregate_counts_shadow_not_injected_not_available_error` |
| Malformed-but-parseable input returns degraded | Empty `context_pack_request_id` check + `test_evaluate_malformed_empty_request_id_returns_degraded` |
| Aligns with Anvil Issue #558 `adoption_status` design | Three statuses match the Anvil canary contract |
