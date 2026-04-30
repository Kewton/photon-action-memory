# Issue 4 Design

## Goal

Implement a local-first SQLite event store for sanitized agent events.

## Approach

- Keep the store stdlib-only with `sqlite3`, `json`, and dataclasses so the M2 sidecar can use it without new dependencies.
- Expose a small API around an `EventStore` class:
  - initialize the schema on construction
  - append one raw event mapping through the sanitizer
  - read events back in timestamp/id order
- Store event envelope fields as queryable SQLite columns:
  - `schema_version`
  - `event_id`
  - `session_id`
  - `turn_id`
  - `repo_id`
  - `timestamp`
  - `event_type`
- Store the sanitized event as canonical JSON in `payload_json`.
- Enforce the sanitizer at the public write boundary by having `append_event` call `sanitize_event_payload` internally.
- Add focused temp-SQLite tests for synthetic event round-trip and fixture privacy checks.

## Sanitizer Scope

Issue 3 owns the full sanitizer. For this issue, the store needs enough sanitizer behavior to guarantee its own acceptance criteria:

- redact secret-like values
- normalize absolute user/tmp paths
- preserve structured JSON values
- mark sanitized payloads with `redaction_status`

