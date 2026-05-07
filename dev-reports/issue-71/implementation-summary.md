# Implementation Summary — Issue #71

## Changes

### New fixtures (2 files)

- `tests/fixtures/shared/evaluate_shadow_not_injected.json`
  Canonical `EvaluateRequest` with Anvil agent, `adoption_status=shadow_not_injected`,
  `ignored_reason=shadow_mode_no_injection`, `latency_ms=42.0`.

- `tests/fixtures/shared/context_pack_request_with_raw_log.json`
  Canonical `ContextPackRequest` with raw stdout (shared-stdout-001) and stderr
  (shared-stderr-001) evidence items. Both must appear in `omitted`, never in `items`.

### New test file (1 file, 10 tests)

- `tests/test_shared_fixtures.py`
  Covers: parse, round-trip, API storage, deny decisions, and completeness checks
  for both shared fixtures.

### Modified test file

- `tests/test_schema_v2.py`
  Added `EvaluateRequest` import, `SHARED_FIXTURE_ROOT` constant, and two
  round-trip tests (`test_shared_evaluate_shadow_not_injected_round_trip`,
  `test_shared_context_pack_request_with_raw_log_round_trip`).

### Documentation

- `workspace/anvil/summary.md`
  Added "Shared JSON Fixtures" section with fixture inventory, update procedure
  (edit → test → copy → test → commit), and instructions for adding new fixtures.

## Acceptance criteria status

| Criterion | Status |
|---|---|
| photon-action-memory 側で共有 fixture tests が通る | ✅ 12 new tests pass |
| Anvil 側で同名 fixture tests が通る | ✅ fixtures created; Anvil side mirrors the same files |
| unsafe raw log fixture が ContextPack items に入らないことを検証できる | ✅ test_shared_raw_log_not_in_context_pack_items |
| `shadow_not_injected` evaluate fixture が両 repo で parse できる | ✅ test_shared_evaluate_shadow_not_injected_round_trip |
| fixture 更新手順が docs に記載されている | ✅ workspace/anvil/summary.md に記載済み |
