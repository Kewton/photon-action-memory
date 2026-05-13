# Implementation Summary - Issue #82

## Objective

Fix the `/v1/summarize` API contract & schema as v0.4.0 P0. Anvil must be
able to express, at the end of a turn, everything the sidecar needs to
build an `ActionSummary`, and the schema must be type-checkable end-to-end.
The generator body is intentionally **out of scope** — only the contract.

## Changes

### `photon_action_memory/api/schema_v2.py`

- Added three new pydantic models:
  - `SummarizePolicy` — generation policy (evidence requirement,
    fact/hypothesis separation, failure / avoid inclusion, size caps).
    All `max_*` fields are `ge=0`; `extra="allow"` keeps room for future
    termination-control flags (e.g. `allow_termination_when_unresolved`)
    referenced by the S2-03 regression motivation.
  - `SummarizeRequest` — minimum required fields are `schema_version`
    (locked to `SchemaVersionV2`) and `request_id`. Optional fields cover
    everything Anvil sends at turn end: `session_id`, `turn_id`, `agent`,
    `repo`, `task`, `summary_level`, `chunk_ids`, `recent_event_ids`,
    `parent_summary_ids`, and `policy`. Reuses `AgentInfo` / `RepoInfo` /
    `TaskState` from the v1 schema, exactly like `ContextPackRequest`.
  - `SummarizeResponse` — required `schema_version`, `request_id`,
    `model_version`, `sidecar_status`. Optional `summary: ActionSummary`,
    `validation: SummaryValidationResult`, and `warnings:
    list[ContextPackWarning]` so callers can pipe the result straight into
    `/v1/summary/upsert` and `/v1/summary/validate`.
- Exported the three new names via `__all__`.

### `photon_action_memory/api/server.py`

- Replaced the M2 501 stub with a real, schema-validated handler:
  - empty payload → pydantic returns **422** automatically.
  - minimum valid payload → **200** with a `SummarizeResponse` whose
    `sidecar_status="not_implemented"` and a single `ContextPackWarning`
    of kind `not_implemented`. This locks the contract while the
    generator is still pending.
- Imported `SummarizeRequest` / `SummarizeResponse`.

### Tests

- `tests/test_schema_v2.py`:
  - `TestSummarizeRequest` — minimal round-trip, full Anvil turn payload,
    required `schema_version` / `request_id`, empty payload rejection,
    `ge=0` enforcement on policy caps, forward-compatible extras
    preserved on request & policy.
  - `TestSummarizeResponse` — minimal round-trip, full payload with
    `ActionSummary` + `SummaryValidationResult` + warning, required
    `schema_version`, forward-compatible extras preserved.
- `tests/test_sidecar_api.py`:
  - Renamed `test_summarize_is_m2_stub` → `test_summarize_empty_payload_returns_422`.
  - Added `test_summarize_minimum_valid_payload_returns_not_implemented_envelope`.
  - Added `test_summarize_full_anvil_turn_payload_validates` to exercise
    the full Anvil request shape end-to-end through `TestClient`.

## Acceptance Criteria Mapping

| Criterion | Status |
|---|---|
| `/v1/summarize` の schema が型検証できる | ✅ `SummarizeRequest` / `SummarizeResponse` are pydantic models; tests round-trip JSON via `model_validate_json` / `model_dump_json`. |
| 空 payload は 422、最小 valid payload は endpoint が処理可能 | ✅ `test_summarize_empty_payload_returns_422` + `test_summarize_minimum_valid_payload_returns_not_implemented_envelope`. |
| Anvil が turn 終了時に送るための必要情報が request で表現できる | ✅ `session_id` / `turn_id` / `agent` / `repo` / `task` / `summary_level` / `chunk_ids` / `recent_event_ids` / `parent_summary_ids` / `policy` are all covered; `test_summarize_full_anvil_turn_payload_validates` exercises them through the API. |
| 既存 `/v1/context/pack` / `/v1/evidence/expand` / `/v1/evaluate` の schema と矛盾しない | ✅ Same `schema_version` literal (`"action-memory.v0.2"`), reused sub-models (`AgentInfo`, `RepoInfo`, `TaskState`, `ActionSummary`, `SummaryValidationResult`, `ContextPackWarning`), and same `SidecarModel` extra-allow base. No existing test broke. |

## Out of Scope (Follow-ups)

- Real summarizer (ActionSummary generation, fidelity check wiring).
- Anvil-side client wiring to actually call `/v1/summarize`.
- Termination-control flags on `SummarizePolicy` for S2-03 regression
  mitigation — schema reserves space via `extra="allow"` but the named
  fields stay default.
