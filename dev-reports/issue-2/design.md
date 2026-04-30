# Issue #2 Design Note

## Goal

Define the first versioned sidecar schema for request, response, and event payloads. The schema must be strict about required contract fields while remaining forward-compatible with optional fields that future Anvil or sidecar versions may add.

## Approach

- Implement Pydantic v2 models in `photon_action_memory/api/schema.py`.
- Require `schema_version` on `SuggestRequest`, `SuggestResponse`, and `SidecarEvent`, and validate it as `action-memory.v1`.
- Model the documented v0.1.0 suggest request/response shapes from `workspace/v0.1.0/01_spec_requirements_architecture.md`.
- Represent Anvil WorkingMemory-like state with a neutral `WorkingMemory` DTO containing active task, constraints, touched files, unresolved errors, precautions, and plan/evidence-oriented optional lists.
- Use `extra="allow"` on schema models so unknown optional fields survive validation and serialization instead of breaking older consumers.
- Add tests for minimal payloads, malformed/missing required fields, unknown optional fields, and an Anvil-style round trip.

## Non-goals

- No FastAPI endpoint implementation in this issue.
- No event persistence, sanitizer, ranking, or MLX adapter behavior.
- No JSON Schema file generation unless a later integration requires it.
