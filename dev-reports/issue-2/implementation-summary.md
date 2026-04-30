# Issue #2 Implementation Summary

## Files Changed

- `photon_action_memory/api/schema.py`
  - Replaced the placeholder with Pydantic v2 schema models for v1 sidecar payloads.
  - Added required `schema_version` validation for `SuggestRequest`, `SuggestResponse`, `SidecarEvent`, and `EventRequest`.
  - Added request DTOs for agent, repo, task, working memory, recent events, and budget.
  - Added response DTOs for suggestions, evidence, and warnings.
  - Added event DTOs for sidecar event ingestion and artifacts.
  - Set the shared schema model config to `extra="allow"` so unknown optional fields are accepted and preserved.
- `tests/test_schema.py`
  - Added focused schema tests for minimal payloads, malformed payloads, missing required fields, unknown optional fields, Anvil-style working memory round trip, and event alias round trip.
- `dev-reports/issue-2/design.md`
  - Recorded the schema-first design before editing.

## Contract Notes

- `schema_version` currently accepts only `action-memory.v1`, matching `photon_action_memory.SCHEMA_VERSION`.
- `WorkingMemory` models the documented neutral fields and allows extra Anvil-specific slots, such as a nested `anvil_working_memory` object.
- `SidecarEvent` accepts either `event_type` or `type` on input for compatibility with the documented compact event shape.
- The implementation is schema-only. API routing, persistence, sanitization, and ranking behavior remain owned by later issues.
