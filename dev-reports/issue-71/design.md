# Design Note — Issue #71: JSON fixture の共有

## Objective

Establish a `tests/fixtures/shared/` directory as the canonical location for
JSON fixtures that both the Anvil repo and photon-action-memory must be able to
parse. When the schema drifts in either direction, the parse tests on both sides
fail — that is the schema-drift signal.

## New files

| Path | Role |
|---|---|
| `tests/fixtures/shared/evaluate_shadow_not_injected.json` | Canonical `EvaluateRequest` with `adoption_status=shadow_not_injected` |
| `tests/fixtures/shared/context_pack_request_with_raw_log.json` | Canonical `ContextPackRequest` with unsafe raw stdout/stderr evidence |
| `tests/test_shared_fixtures.py` | 10 focused tests for the two shared fixtures |

## Modified files

| Path | Change |
|---|---|
| `tests/test_schema_v2.py` | Import `EvaluateRequest`; add `SHARED_FIXTURE_ROOT`; add two round-trip tests under Issue #71 section |
| `workspace/anvil/summary.md` | New "Shared JSON Fixtures" section with update procedure |

## Test coverage

### `evaluate_shadow_not_injected.json`
- Parses as `EvaluateRequest` with correct `adoption_status`, `ignored_reason`, `latency_ms`
- Round-trips through `model_dump_json → model_validate_json`
- Stores via `POST /v1/evaluate`; payload stored with correct fields

### `context_pack_request_with_raw_log.json`
- Parses as `ContextPackRequest`
- Round-trips without data loss
- `POST /v1/context/pack` returns empty `items` (raw evidence denied)
- Both raw evidence items appear in `omitted`; `admission_decisions` contains deny decisions

### Cross-fixture completeness
- Parametrised test confirms each shared fixture file is valid JSON with `schema_version` set to `action-memory.v0.2`

## Non-goals
- No changes to the Anvil repo (out of scope; done by Anvil-side worker)
- No production code changes — all logic is already implemented
- No symlinks or external sync tooling — the update procedure in docs is sufficient
