# Design Note - Issue #73: Anvil Operations Docs

## Objective

Document the day-to-day Anvil integration workflow for photon-action-memory:
starting the local sidecar, running API smoke checks, configuring Anvil
shadow/canary mode, updating shared fixtures, and troubleshooting failures.

## Scope

This issue is documentation-only. The API and rollout helpers already exist:

- `photon_action_memory/api/server.py` exposes `/health`,
  `/v1/context/pack`, `/v1/evidence/expand`, `/v1/summary/upsert`,
  `/v1/summary/validate`, and `/v1/evaluate`.
- `workspace/anvil/summary.md` already captures shared fixture and rollout
  references from Issues #71 and #72.
- `workspace/anvil/rollout_policy.md` already defines the rollout gates.

## Design

Add two docs:

- `docs/photon-action-memory.md`: photon-side sidecar quickstart and API smoke
  checks that can be run without the Anvil repository.
- `docs/anvil-integration.md`: Anvil-facing operations guide with env/defaults,
  shadow/canary/rollback checklists, fixture update procedure, and split
  troubleshooting responsibilities.

Update navigation:

- Link the docs from `README.md`.
- Link the docs from `workspace/anvil/summary.md`.

## Safety Notes

- Use `127.0.0.1:18765` as the example sidecar URL.
- Do not use port 3000 in the documentation.
- Keep source-of-truth boundaries explicit:
  photon docs own sidecar/API contract; Anvil docs own Anvil runtime config and
  prompt/eval log behavior.

