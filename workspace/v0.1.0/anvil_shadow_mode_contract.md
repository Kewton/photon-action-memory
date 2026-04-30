# Anvil Shadow-Mode Sidecar Contract

## Purpose

This contract lets Anvil call PHOTON Action Memory in shadow mode without
delegating final control to the sidecar. The sidecar returns suggestions; Anvil
records the actual next action and whether that action matched the suggestions.

Canonical fixtures:

- `tests/fixtures/anvil_shadow_mode/suggest_request.json`
- `tests/fixtures/anvil_shadow_mode/suggest_response.json`
- `tests/fixtures/anvil_shadow_mode/event_request.json`
- `tests/fixtures/anvil_shadow_mode/evaluate_request.json`

## Flow

1. Before choosing the next actor-loop action, Anvil sends `POST /v1/suggest`.
2. Anvil executes its normal next action regardless of the sidecar result.
3. Anvil records a `shadow_evaluation` event through `POST /v1/events`.
4. Anvil batches shadow outcome records through `POST /v1/evaluate`.

`/v1/evaluate` can remain a stub while Anvil integration is developed. The
fixture fixes the schema Anvil should produce once evaluation ingestion is
enabled.

## Required Fields

Each shadow evaluation record must include:

- `request_id`: the original suggest request id.
- `suggestion_ids`: stable ids from the sidecar response.
- `actual_next_action`: the action Anvil actually took.
- `matched`: whether the actual action adopted or matched a suggestion.
- `ignored_reason`: nullable reason when suggestions were ignored.
- `outcome`: `success`, `failure`, `partial`, or `unknown`.
- `latency_ms`: sidecar call latency measured by the caller.
- `sidecar_status`: `ok`, `timeout`, `error`, `unavailable`, or `not_called`.

Anvil-specific working-memory details should stay in metadata / extra fields so
the core schema remains usable by other agents.
