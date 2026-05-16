# Issue #115 — design note

## Problem

`POST /v1/evaluate` (`server.py::evaluate`) builds the persisted payload from a
fixed allowlist of named fields on `ContextPackEvalEvent`. Anvil PR #596 began
sending two new fields — `summary_ids_adopted` (list[str]) and
`summary_ids_adopted_truncated` (bool) — but only the former is defined on the
schema, and neither was originally persisted, blocking per-seed feedback
aggregation downstream.

## Current state (worktree snapshot)

- `ContextPackEvalEvent.summary_ids_adopted` already exists
  (`photon_action_memory/api/schema_v2.py:567`).
- `server.py::evaluate` already copies `evt.summary_ids_adopted` into the
  persisted payload (`photon_action_memory/api/server.py:362`) and uses it for
  `_summary_store.record_outcomes(...)`.
- `summary_ids_adopted_truncated` does **not** exist on the schema, so it is
  silently dropped by Pydantic (`extra="ignore"` semantics inherited from
  `SidecarModel`) and never reaches storage.
- `tests/test_evaluate.py` has no regression covering either of the two
  per-seed fields.

## Change

1. `schema_v2.ContextPackEvalEvent`: add
   `summary_ids_adopted_truncated: bool = False` immediately after
   `summary_ids_adopted` so the schema mirrors what Anvil sends.
2. `server.py::evaluate`: include `summary_ids_adopted_truncated` in the
   storage payload alongside `summary_ids_adopted`. Allowlist stays explicit
   so raw stdout/stderr are still excluded (`test_evaluate_payload_excludes_
   raw_stdout_stderr` continues to pass).
3. `tests/test_evaluate.py`: extend the existing `test_evaluate_logs_event_to
   _store`-style asserts so the stored payload contains both fields. Also
   cover the back-compat case (legacy Anvil omits both → defaults survive).

## Out of scope

- Aggregation downstream (`anvil_feedback`, `context_pack_log`) — those modules
  already use `extra="ignore"` and do not need a new column for this fix.
- Migration of historical events; older payloads simply lack the keys.

## Backward compatibility

`default_factory=list` and `default=False` mean Anvil instances on PR #596 or
older keep working unchanged: the request validates, the payload is stored
with empty/false defaults, and existing consumers ignore the unknown keys.
