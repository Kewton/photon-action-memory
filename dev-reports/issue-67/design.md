# Design Note — Issue #67: /v1/evaluate Anvil Support

## Objective

Extend `POST /v1/evaluate` to handle Anvil's turn result with shadow/canary rollout.
Anvil Issue #558 introduced three new `adoption_status` values not present in the
original `ContextPackAdoptionStatus` Literal.

## Changes

### 1. Schema — `ContextPackAdoptionStatus` (schema_v2.py)

Added three Anvil-specific statuses to the Literal:

| Status | Meaning |
|---|---|
| `shadow_not_injected` | Shadow mode ran; context pack was not injected |
| `not_available` | Sidecar was unreachable or timed out |
| `error` | Sidecar returned an error response |

The existing `| str` fallback in `ContextPackEvalEvent.adoption_status` already accepts
unknown strings; the Literal addition makes the known Anvil values explicit and
IDE/docs-visible.

### 2. Aggregate — `ContextPackAdoptionReport` (context_pack_log.py)

Added three optional integer counters (default 0) to the aggregate report:
`shadow_not_injected_count`, `not_available_count`, `error_count`.

`aggregate_context_pack_eval()` now counts these statuses alongside the existing
`adopted`, `ignored`, `partial` counts.

Existing fields and adoption_rate formula are unchanged.

### 3. Server — malformed-but-parseable detection (server.py)

Added a pre-log check: if `context_pack_event.context_pack_request_id` is empty, a
`malformed_eval_input` warning is appended and the response `status` is set to
`"degraded"` (the event is still logged, so `logged=1`).

The evaluate payload is explicitly constructed from named fields only, ensuring raw
stdout/stderr passed as extra fields are never persisted.

### 4. Fixtures

- `tests/fixtures/v0.2/evaluate_anvil_shadow.json` — Anvil shadow fixture with
  `shadow_not_injected` status.
- `tests/fixtures/v0.2/context_pack_adoption_log_anvil.json` — Multi-turn log with
  all three new statuses for aggregate testing.

## Invariants Preserved

- All existing tests continue to pass (623 passed, 1 skipped).
- No breaking changes to existing fixture schemas.
- The raw stdout/stderr exclusion policy is now documented in a comment and
  covered by an explicit test.
