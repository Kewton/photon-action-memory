# Issue #115 — implementation summary

## Files changed

- `photon_action_memory/api/schema_v2.py`
  - Added `summary_ids_adopted_truncated: bool = False` to
    `ContextPackEvalEvent` so Anvil PR #596's truncation flag is accepted by
    the schema and surfaced as a typed attribute.

- `photon_action_memory/api/server.py`
  - Extended the `/v1/evaluate` payload built in `evaluate(...)` to include
    `"summary_ids_adopted_truncated": evt.summary_ids_adopted_truncated`.
    `summary_ids_adopted` was already on the payload; both fields now travel
    together to `event_store.append(...)`.

- `tests/test_evaluate.py`
  - `test_evaluate_persists_summary_ids_adopted_fields` — asserts the stored
    payload echoes the request's `summary_ids_adopted` list and the
    `summary_ids_adopted_truncated` boolean.
  - `test_evaluate_legacy_anvil_omits_summary_ids_fields` — back-compat:
    a request that omits both fields stores `[]` and `False`.

## What stays the same

- The payload allowlist remains explicit; raw stdout/stderr from
  `model_extra` are still filtered (existing
  `test_evaluate_payload_excludes_raw_stdout_stderr` still passes).
- `_summary_store.record_outcomes(...)` continues to use
  `evt.summary_ids_adopted` as before — no behavioural change there.
- `ContextPackEvalRecord` (eval/context_pack_log.py) keeps
  `extra="ignore"`, so the new truncation key is harmless to legacy
  aggregation paths.

## Behavioural notes

- For Anvil clients on PR #596+: both fields now round-trip through
  `/v1/evaluate` into the events table.
- For pre-#596 clients: requests validate as before; storage records
  `summary_ids_adopted=[]` and `summary_ids_adopted_truncated=False`.
