# Verification - Issue #82

## Focused Tests

```
python -m pytest tests/test_schema_v2.py tests/test_sidecar_api.py -x -q
```

Result: **78 passed in 0.32s**

New coverage:

- `tests/test_schema_v2.py::TestSummarizeRequest`
  - `test_minimal_round_trip`
  - `test_full_anvil_turn_payload`
  - `test_schema_version_required`
  - `test_request_id_required`
  - `test_empty_payload_fails`
  - `test_policy_max_fields_reject_negative`
  - `test_unknown_policy_fields_preserved`
  - `test_unknown_request_fields_preserved`
- `tests/test_schema_v2.py::TestSummarizeResponse`
  - `test_minimal_round_trip`
  - `test_full_payload_with_summary_and_validation`
  - `test_schema_version_required`
  - `test_unknown_fields_preserved`
- `tests/test_sidecar_api.py`
  - `test_summarize_empty_payload_returns_422`
  - `test_summarize_minimum_valid_payload_returns_not_implemented_envelope`
  - `test_summarize_full_anvil_turn_payload_validates`

## Broader Suite (shared contracts touched)

```
python -m pytest tests/ -x -q --ignore=tests/integration
```

Result: **808 passed in 2.77s**

```
python -m pytest tests/integration -x -q
```

Result: **1 skipped** (MLX smoke is opt-in).

## Acceptance Criteria Mapping

| Criterion | Evidence |
|---|---|
| `/v1/summarize` schema is type-checkable | pydantic round-trip tests in `TestSummarizeRequest` / `TestSummarizeResponse`. |
| Empty payload → 422 | `test_summarize_empty_payload_returns_422` |
| Minimum valid payload is processable | `test_summarize_minimum_valid_payload_returns_not_implemented_envelope` — sidecar returns 200 with `sidecar_status="not_implemented"` envelope. |
| Anvil turn-end info expressible | `test_summarize_full_anvil_turn_payload_validates` + `TestSummarizeRequest.test_full_anvil_turn_payload` cover `session_id` / `turn_id` / `agent` / `repo` / `task` / `summary_level` / `chunk_ids` / `recent_event_ids` / `parent_summary_ids` / `policy`. |
| No conflict with `/v1/context/pack`, `/v1/evidence/expand`, `/v1/evaluate` schemas | Whole suite (808 tests, including `test_anvil_*`, `test_evaluate`, `test_context_pack`, `test_evidence_expander`, `test_schema_v2`) passes. Shared sub-models (`AgentInfo`, `RepoInfo`, `TaskState`, `ActionSummary`, `SummaryValidationResult`, `ContextPackWarning`) and the `action-memory.v0.2` schema version literal are reused. |
