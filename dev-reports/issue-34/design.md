# Issue 34 Design: ActionChunker

## Context

Issue #34 is Milestone 2 of the v0.2.0 plan: implement `ActionChunker`, the component
that groups sanitized `StoredEvent` records from the local SQLite store into `ActionChunk`
units as defined in `photon_action_memory/api/schema_v2.py`.

The architecture document (`workspace/v0.2.0/04_architecture.md`, section 2) specifies:

> Recent events are grouped by intent / turn / time / tool type.
> Sidecar creates ActionChunk. ActionChunk records `event_ids` and coarse outcome.

## Inputs and Outputs

**Input:** `Sequence[StoredEvent]` - already sanitized by `EventStore` before storage.
No additional sanitization is needed in the chunker itself.

**Output:** `list[ActionChunk]` from `schema_v2.ActionChunk`.

## Grouping Strategy

Default: one `ActionChunk` per `(session_id, turn_id)` pair, preserving first-seen
order. Events within a turn represent a cohesive agent action (e.g., one tool call
plus its result), so turn-level grouping is the natural boundary.

`chunk_one()` is provided for callers that want all events collapsed into one chunk
regardless of turn boundaries (e.g., summarizing a short session).

## Determinism

`chunk_id` is a 16-hex-character prefix of SHA-256 over newline-joined **sorted**
event IDs. This ensures:

- Same event set -> same `chunk_id` across runs.
- List insertion order does not affect the ID.
- Different event sets reliably produce different IDs (collision probability negligible).

## Inference Heuristics

### kind
Majority vote over `_EVENT_KIND_MAP[event_type.lower()]`. Ties broken alphabetically
for stability. Falls back to `"other"` for unrecognized types.

### outcome
Scan events in reverse order. Accept the first `payload["outcome"]` that is a valid
`ChunkOutcome` literal, or map `payload["status"]` via a fixed lookup table
(`success`/`ok`/`passed` -> `useful`, `error`/`failed`/`failure` -> `failed`).
Default: `"unknown"`.

### risk
Scan events for an explicit `payload["risk"]` that is a valid `RiskLevel` literal.
Fallback: if the inferred `kind` is `edit_attempt` or `failure_reproduction`, return
`"medium"`. Otherwise `None`.

### redaction_status
`"redacted"` if any event payload has `redaction_status == "redacted"`.
`"clean"` only if every event payload has `redaction_status == "clean"`.
`"unknown"` otherwise (including missing values).

## Module Location

`photon_action_memory/memory/chunks.py` - alongside `store.py` and `sanitizer.py`
in the memory sub-package, matching the planned package structure in architecture doc
section 9.

## Non-Goals

- No model integration (model is optional per architecture doc section 8).
- No persistence of chunks (storage is caller's responsibility).
- No context admission or token budgeting (out of scope for this milestone).
