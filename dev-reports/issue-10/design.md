# Issue #10 Design: Anvil shadow-mode contract fixtures

## Goal

Fix a minimal, schema-validated integration contract that Anvil can use to call the sidecar in shadow mode and report what happened after the agent chooses its real next action.

## Shape

- Keep `SuggestRequest` / `SuggestResponse` as the request and response contract for `POST /v1/suggest`.
- Add optional stable `id` fields to `Suggestion` so responses can be joined to later shadow evaluation records without breaking existing callers.
- Add neutral evaluation DTOs for `POST /v1/evaluate` contract data:
  - request id
  - suggestion ids returned by sidecar
  - actual next action taken by Anvil
  - matched / ignored reason
  - outcome
  - latency in milliseconds
  - sidecar status
- Store Anvil-specific details in fixture metadata / extra fields rather than making the core schema Anvil-only.

## Fixtures

Add fixed JSON fixtures under `tests/fixtures/anvil_shadow_mode/`:

- `suggest_request.json`: Anvil shadow-mode input with L2 working memory and recent events.
- `suggest_response.json`: sidecar guidance with stable suggestion ids and evidence.
- `event_request.json`: event-store compatible shadow evaluation event.
- `evaluate_request.json`: adoption/ignored/outcome event tying the request and response to the actual next action.

Tests load those files and validate them through Pydantic models, including round-trip checks and assertions for adoption / ignored / outcome tracking fields.

## Scope boundaries

`/v1/evaluate` remains an M2 stub in the server. This issue fixes the contract and fixtures Anvil can build against; persistence and metric computation stay with later M6 evaluation work.
