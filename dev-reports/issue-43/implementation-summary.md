# Issue #43 — Anvil ContextPack Integration Contract: Implementation Summary

## Scope

Add a neutral ContextPack integration contract for `POST /v1/context/pack` before
LLM prompt construction, optional `POST /v1/evidence/expand` when more detail is
needed, ContextPack adoption/ignored/outcome logging through `POST /v1/evaluate`,
and privacy-safe neutral fixtures.

---

## Changes

### 1. Schema — `photon_action_memory/api/schema_v2.py`

Added three new models under a `POST /v1/evaluate` section:

| Model | Purpose |
|---|---|
| `ContextPackEvalEvent` | One turn's ContextPack adoption event: `adoption_status`, `ignored_reason`, `evidence_expand_requested`, `evidence_ids_expanded`, `items_adopted_count`, `items_ignored_count`, `outcome`, `outcome_detail`, `latency_ms` |
| `EvaluateRequest` | Request body for `POST /v1/evaluate`; carries an optional `context_pack_event` |
| `EvaluateResponse` | Response body: `logged` count, `status`, `warnings` |

`ContextPackAdoptionStatus = Literal["adopted", "ignored", "partial"]` added as a
named type alias.  All three models added to `__all__`.

### 2. Server — `photon_action_memory/api/server.py`

Replaced the `501 evaluate_stub` with a working `POST /v1/evaluate` endpoint:

- If `context_pack_event` is present, stores a `type=context_pack_eval` event
  in the SQLite event store and returns `logged=1`.
- Fail-open: errors are caught, logged to `warnings`, and `status="degraded"`.
- No event → `logged=0`, `status="ok"`.

### 3. Eval module — `photon_action_memory/eval/context_pack_log.py` (new)

Provides offline aggregation of ContextPack eval records:

| Symbol | Purpose |
|---|---|
| `ContextPackEvalRecord` | Normalized single-turn record (pydantic, `extra="ignore"`) |
| `ContextPackAdoptionReport` | Aggregate: adoption rate, evidence-expand rate, task success rate, ignored-reason counts, outcome counts |
| `aggregate_context_pack_eval(records)` | Builds `ContextPackAdoptionReport` from a sequence of records or raw dicts |

### 4. Integration contract — `photon_action_memory/integration/context_pack_contract.py` (new)

Defines the neutral three-step calling sequence:

1. `POST /v1/context/pack` — required, before prompt assembly
2. `POST /v1/evidence/expand` — optional, when items carry `expand_policy="on_demand_only"`
3. `POST /v1/evaluate` — required, after the turn completes

| Symbol | Purpose |
|---|---|
| `IntegrationStepKind` | `Literal["context_pack", "evidence_expand", "evaluate"]` |
| `IntegrationStep` | Frozen dataclass: kind, endpoint, when, required |
| `IntegrationContract` | Frozen dataclass: steps tuple + invariants tuple |
| `CONTEXT_PACK_CONTRACT` | Module-level constant instance |
| `REQUIRED_STEPS` / `OPTIONAL_STEPS` | Frozensets for quick membership checks |
| `validate_call_sequence(step_kinds)` | Returns a list of contract violations; empty = valid |

Also added `photon_action_memory/integration/__init__.py`.

### 5. Fixtures — `tests/fixtures/v0.2/` (three new files)

| File | Content |
|---|---|
| `evaluate_context_pack_adopted.json` | POST /v1/evaluate body with `adoption_status="adopted"`, `outcome="success"` |
| `evaluate_context_pack_ignored.json` | POST /v1/evaluate body with `adoption_status="ignored"`, `ignored_reason="existing_plan_had_higher_priority"` |
| `context_pack_adoption_log.json` | Five-record multi-turn fixture for `aggregate_context_pack_eval` testing |

All fixtures are privacy-safe: no real file paths, user data, or code snippets.

### 6. Tests — `tests/test_evaluate.py` (new, 30 tests)

Covers:

- HTTP endpoint: adopted / ignored / no-event / logs-to-store / evidence-expand fields
- Schema round-trip: `EvaluateRequest`, `EvaluateResponse`
- Fixture validation: all three new fixtures parse correctly
- `aggregate_context_pack_eval`: empty, all-adopted, mixed, from fixture file
- `validate_call_sequence`: valid complete, valid with expand, missing steps, wrong order, expand without pack
- Contract structure: required steps present, optional steps present, invariants non-empty, required flags, endpoints

---

## Design decisions

**Agent-neutral contract**: `context_pack_contract.py` never imports or references
Anvil internals.  The module docstring names Anvil as a concrete example only.

**Fail-open evaluate endpoint**: matches the existing fail-open pattern in
`/v1/context/pack`; eval errors must not disrupt the calling agent's turn.

**Flat event store**: `ContextPackEvalEvent` is stored as a plain dict via the
existing `SQLiteEventStore.append()` so it can be replayed or aggregated later
without schema migration.

**Separation of concerns**: HTTP schema (`schema_v2.py`), offline aggregation
(`eval/context_pack_log.py`), and the calling contract
(`integration/context_pack_contract.py`) are in separate modules so each can
evolve independently.
