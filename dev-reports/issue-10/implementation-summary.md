# Issue #10 Implementation Summary

## Changed

- Added explicit shadow evaluation DTOs in `photon_action_memory/api/schema.py`:
  - `ActualNextAction`
  - `EvaluationRecord`
  - `EvaluationRequest`
  - `EvaluationResponse`
  - `SidecarStatus`
  - `ShadowOutcome`
- Added optional `Suggestion.id` so sidecar responses can be joined to later shadow evaluation records.
- Added fixed Anvil shadow-mode fixtures:
  - `tests/fixtures/anvil_shadow_mode/suggest_request.json`
  - `tests/fixtures/anvil_shadow_mode/suggest_response.json`
  - `tests/fixtures/anvil_shadow_mode/event_request.json`
  - `tests/fixtures/anvil_shadow_mode/evaluate_request.json`
- Added schema tests that load and validate the fixtures through the Pydantic models.
- Added `workspace/v0.1.0/anvil_shadow_mode_contract.md` as the handoff integration spec for the Anvil-side issue.
- Updated v0.1.0 architecture and development-plan docs with the shadow evaluation contract and fixture locations.

## Notes

`/v1/evaluate` remains a stub. This issue fixes the schema and fixture contract that Anvil can implement against; ingestion and metrics computation remain later M6 work.
