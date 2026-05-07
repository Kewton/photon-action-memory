# Anvil Integration Operations

This guide describes how Anvil should operate with the
photon-action-memory sidecar in shadow, canary, and rollback workflows.

## Architecture

```text
Anvil
  -> HTTP calls to photon-action-memory sidecar
  -> local SQLite event and summary stores
  -> context pack, evidence expansion, rollout metrics
```

The sidecar is local-first and fail-open. If it is unavailable, Anvil continues
the user turn without injected memory and records enough evaluation data to
debug the failure later.

## Source Of Truth Boundaries

| Area | Source of truth |
|---|---|
| Sidecar process, endpoint shapes, API smoke checks | `docs/photon-action-memory.md` |
| Anvil env/defaults, prompt injection, eval log fields | Anvil repository docs |
| Shared JSON fixtures | `tests/fixtures/shared/` in both repositories |
| Rollout gates | `workspace/anvil/rollout_policy.md` |

## Environment Defaults

These values must stay aligned with the Anvil docs and defaults.

| Variable | Shadow default | Purpose |
|---|---:|---|
| `ANVIL_PHOTON_ENABLED` | `true` | Enables Anvil calls to the sidecar. |
| `ANVIL_PHOTON_URL` | `http://127.0.0.1:18765` | Local sidecar URL. Do not use port 3000. |
| `ANVIL_PHOTON_SHADOW_MODE` | `true` | Build/log context packs without prompt injection. |
| `ANVIL_PHOTON_CANARY` | `false` | Live injection stays disabled during shadow mode. |
| `ANVIL_PHOTON_TIMEOUT_MS` | `500` | Sidecar request timeout. |
| `ANVIL_PHOTON_MAX_MEMORY_TOKENS` | `1200` | Context pack memory budget. |
| `ANVIL_PHOTON_MAX_EVIDENCE_CHARS` | `4000` | Evidence expansion character budget. |

Shadow mode:

```bash
export ANVIL_PHOTON_ENABLED=true
export ANVIL_PHOTON_URL=http://127.0.0.1:18765
export ANVIL_PHOTON_SHADOW_MODE=true
export ANVIL_PHOTON_CANARY=false
export ANVIL_PHOTON_TIMEOUT_MS=500
export ANVIL_PHOTON_MAX_MEMORY_TOKENS=1200
export ANVIL_PHOTON_MAX_EVIDENCE_CHARS=4000
```

Canary mode:

```bash
export ANVIL_PHOTON_ENABLED=true
export ANVIL_PHOTON_URL=http://127.0.0.1:18765
export ANVIL_PHOTON_SHADOW_MODE=false
export ANVIL_PHOTON_CANARY=true
```

## API Contract

| Endpoint | Anvil call timing | Expected behavior |
|---|---|---|
| `GET /health` | Startup and diagnostics | Returns sidecar health. |
| `POST /v1/summary/upsert` | After Anvil summarizes useful turn history | Stores `ActionSummary` for later retrieval. |
| `POST /v1/context/pack` | Before prompt assembly | Returns admitted memory items and denial decisions. |
| `POST /v1/evidence/expand` | Optional, after context pack selection | Expands selected evidence only; raw output remains denied in Anvil profile. |
| `POST /v1/evaluate` | After every turn | Logs adoption status, outcome, and rollout signals. |

Required sequence for a turn:

```text
context_pack -> optional evidence_expand -> evaluate
```

`evaluate` remains required even in shadow mode because rollout metrics depend
on shadow adoption and fail-open data.

## Shadow Mode Checklist

All items must be true before collecting rollout evidence.

- Sidecar health succeeds at `http://127.0.0.1:18765/health`.
- Anvil config has `ANVIL_PHOTON_ENABLED=true`.
- Anvil config has `ANVIL_PHOTON_SHADOW_MODE=true`.
- Anvil config has `ANVIL_PHOTON_CANARY=false`.
- Anvil calls `/v1/context/pack` before prompt assembly.
- Anvil does not inject returned context into the live prompt.
- Anvil calls `/v1/evaluate` after the turn.
- Evaluate records use `adoption_status=shadow_not_injected`.
- `raw_tool_tokens_in_prompt` remains `0`.
- Shared fixture tests pass in both repositories.

## Canary Checklist

Move to canary only after the rollout gates pass.

- `total_turns >= 10`.
- `raw_tool_tokens_in_prompt == 0`.
- `fail_open_incident_rate <= 0.05`.
- The latest shared fixture tests pass in both repositories.
- Anvil can disable canary without code changes.
- Operators know where event and eval logs are stored.

Enable canary with:

```bash
export ANVIL_PHOTON_SHADOW_MODE=false
export ANVIL_PHOTON_CANARY=true
```

During canary, continue to call `/v1/evaluate` after every turn and monitor:

- fail-open incidents
- raw tool token leakage
- adoption rate
- stale or contradicted summary incidents
- latency versus `ANVIL_PHOTON_TIMEOUT_MS`

## Rollback Checklist

Rollback is immediate if any of these are observed:

- `raw_tool_tokens_in_prompt > 0`
- `fail_open_incident_rate > 0.05`
- sidecar failures repeatedly exceed the timeout budget
- prompt injection is enabled in a session that should be shadow-only

Rollback to shadow:

```bash
export ANVIL_PHOTON_CANARY=false
export ANVIL_PHOTON_SHADOW_MODE=true
```

Disable the integration:

```bash
export ANVIL_PHOTON_ENABLED=false
```

Also check persistent Anvil config such as `.anvil/config`; environment
variables and checked-in/local config must not disagree.

## Shared Fixture Update Procedure

1. Edit the fixture under `tests/fixtures/shared/` in this repository.
2. Run photon-side fixture tests:
   ```bash
   python -m pytest tests/test_shared_fixtures.py tests/test_schema_v2.py -k shared -q
   ```
3. Copy the same file to the Anvil repository at the same relative path.
4. Run the Anvil-side shared fixture tests.
5. Commit both repository updates as a PR pair and mention the changed fixture
   file in both PR descriptions.

## Troubleshooting

### Anvil Responsibility

- Confirm `ANVIL_PHOTON_URL` is `http://127.0.0.1:18765`.
- Confirm Anvil is not using port 3000 for photon-action-memory.
- Confirm `ANVIL_PHOTON_TIMEOUT_MS=500` unless intentionally overridden.
- Confirm shadow sessions set `ANVIL_PHOTON_CANARY=false`.
- Confirm canary sessions set `ANVIL_PHOTON_SHADOW_MODE=false`.
- Confirm Anvil writes eval records after every turn.
- Confirm prompt logs show no raw stdout/stderr injected into the prompt.
- Confirm `.anvil/config` does not override the environment unexpectedly.

### photon-action-memory Responsibility

- Confirm `/health` returns `status=ok`.
- Confirm the event DB path from `PHOTON_ACTION_MEMORY_DB` is writable.
- Confirm the summary DB path from `PHOTON_ACTION_MEMORY_SUMMARY_DB` is writable.
- Confirm `/v1/context/pack` returns 200 or a fail-open response, not an
  uncaught process failure.
- Confirm raw stdout/stderr are denied by context-pack admission decisions.
- Confirm `/v1/evaluate` returns `logged=1` for context pack events.
- Confirm rollout metrics are generated from the same evaluate batch used for
  the canary decision.

## Operational Smoke

Use the photon-side smoke checks before debugging Anvil behavior:

```bash
python -m uvicorn photon_action_memory.api.server:app \
  --host 127.0.0.1 \
  --port 18765
```

Then run the commands in `docs/photon-action-memory.md`:

- `GET /health`
- `POST /v1/context/pack`
- `POST /v1/evaluate`
- `POST /v1/summary/upsert`

