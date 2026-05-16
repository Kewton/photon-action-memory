# photon-action-memory Sidecar Operations

This document is the photon-action-memory side of the Anvil integration. It is
enough to start the local sidecar and run API smoke checks without opening the
Anvil repository.

## Source Of Truth

- Sidecar process and API contract: this repository.
- Anvil runtime configuration and prompt/eval log behavior: Anvil docs.
- Shared fixture files: `tests/fixtures/shared/` in both repositories.

Use `127.0.0.1:18765` for local examples. Do not use port 3000 for this
sidecar.

## Install

```bash
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

## Local Storage

The sidecar stores events and summaries in SQLite. Defaults are under the
system temp directory.

| Variable | Default |
|---|---|
| `PHOTON_ACTION_MEMORY_DB` | `$TMPDIR/photon-action-memory/events.sqlite` |
| `PHOTON_ACTION_MEMORY_SUMMARY_DB` | `$TMPDIR/photon-action-memory/summaries.sqlite` |

For repeatable smoke checks, set explicit paths:

```bash
export PHOTON_ACTION_MEMORY_DB="$TMPDIR/photon-action-memory/events.sqlite"
export PHOTON_ACTION_MEMORY_SUMMARY_DB="$TMPDIR/photon-action-memory/summaries.sqlite"
```

## Start The Sidecar

```bash
python -m uvicorn photon_action_memory.api.server:app \
  --host 127.0.0.1 \
  --port 18765
```

Expected startup state:

- The process listens on `http://127.0.0.1:18765`.
- No Anvil process is required for the photon-side smoke checks.
- The sidecar is fail-open for integration routes; callers should keep their own
  turn execution path independent of this process.

### Optional PHOTON Checkpoint Scorer

The default scorer is deterministic and requires no PHOTON checkpoint. To test
the PHOTON/MLX scorer path, point the sidecar at a local runtime checkpoint:

```bash
PHOTON_ACTION_MEMORY_CHECKPOINT=/path/to/checkpoint \
python -m uvicorn photon_action_memory.api.server:app \
  --host 127.0.0.1 \
  --port 18765
```

For strict local verification of `state.json` and `weights.npz` hashes:

```bash
PHOTON_ACTION_MEMORY_CHECKPOINT=/path/to/checkpoint \
PHOTON_ACTION_MEMORY_CHECKPOINT_STRICT=true \
python -m uvicorn photon_action_memory.api.server:app \
  --host 127.0.0.1 \
  --port 18765
```

Runtime checkpoint directories use this shape:

```text
checkpoint/
  manifest.json
  state.json
  weights.npz
  integrity.json
```

`manifest.json` carries the small Action Memory scoring state:

```json
{
  "format": "photon-action-memory.mlx.v1",
  "model_version": "action-memory-photon-...",
  "state": {
    "bias": 0.5,
    "action_weights": {},
    "file_weights": {},
    "evidence_weights": {}
  }
}
```

Large checkpoints and model weights must stay outside git. The committed
checkpoint under `tests/fixtures/photon/checkpoints/action_memory_tiny/` is a
tiny CI fixture only; it is not a production model.

Fallback matrix:

| State | Expected behavior |
|---|---|
| checkpoint unset | deterministic scorer |
| checkpoint valid + MLX available | PHOTON scorer |
| checkpoint missing | deterministic fallback + `photon_unavailable` warning |
| checkpoint invalid | deterministic fallback + `photon_unavailable` warning |
| MLX unavailable | deterministic fallback + `photon_unavailable` warning |
| strict integrity mismatch | deterministic fallback + `photon_unavailable` warning |

To build a small local checkpoint from normalized eval/feedback records:

```bash
python scripts/build_action_memory_checkpoint.py records.json \
  --output /tmp/photon-action-memory/checkpoints/local-v1 \
  --model-version action-memory-local-v1
```

The records file may be a JSON list or an object with a `records` list. Each
record can include `kind`, `key`/`target`/`evidence_id`/`action`, and either an
explicit `weight` or an `adopted` boolean.

## API Smoke Checks

Run these from the repository root while the sidecar is running.

### Health

```bash
curl -fsS http://127.0.0.1:18765/health
```

Expected shape:

```json
{"status":"ok","schema_version":"action-memory.v1"}
```

### Context Pack

This shared fixture includes raw stdout/stderr evidence. The raw evidence must
not be returned as prompt items.

```bash
curl -fsS \
  -H 'content-type: application/json' \
  -X POST \
  --data @tests/fixtures/shared/context_pack_request_with_raw_log.json \
  http://127.0.0.1:18765/v1/context/pack
```

Expected checks:

- HTTP status is 200.
- `sidecar_status` is `ok` or `degraded`; `fail-open` means the caller should
  continue without injected memory and inspect sidecar logs.
- `context_pack.items` does not include raw stdout/stderr content.
- `admission_decisions` explain denied raw evidence.

### Evaluate

This logs a shadow-mode turn without prompt injection.

```bash
curl -fsS \
  -H 'content-type: application/json' \
  -X POST \
  --data @tests/fixtures/shared/evaluate_shadow_not_injected.json \
  http://127.0.0.1:18765/v1/evaluate
```

Expected checks:

- `status` is `ok`.
- `logged` is `1`.
- The stored event has `adoption_status=shadow_not_injected`.

### Summarize (v0.4.0 P1 / P2)

`/v1/summarize` produces an `ActionSummary` from buffered chunks. It is the
M2 stub (HTTP 501) until v0.4.0 P1 (Issue #86) lands. The integration smoke
expects the v0.4.0 contract and is reproducible today with a graceful 501
fallback that uses a fixture in place of the live response.

Request envelope:

```json
{
  "schema_version": "action-memory.v0.2",
  "request_id": "smoke-summarize-<short>",
  "session_id": "anvil-smoke-<scenario>-001",
  "chunk_ids": ["anvil-eval-<scenario>-chunk-001"],
  "summary_level": "chunk",
  "policy": {
    "require_evidence_ids": true,
    "separate_fact_and_hypothesis": true,
    "include_failed_attempts": true,
    "include_avoid_guidance": true
  }
}
```

Expected response (post-P1):

```json
{
  "schema_version": "action-memory.v0.2",
  "request_id": "smoke-summarize-<short>",
  "summary": { "summary_id": "<id>", "...": "..." },
  "validation": { "status": "valid", "score": 0.94 }
}
```

End-to-end smoke runner:

```bash
python3 scripts/anvil_v1_summarize_smoke.py --scenario S3-01
```

The runner drives the full turn lifecycle against `127.0.0.1:18765`:
`summarize → summary/upsert → context/pack → evidence/expand → evaluate`.
If `/v1/summarize` is the 501 stub, the runner records
`status=summarize_stub` and continues from `/v1/summary/upsert`. Pass
`--scenario` multiple times to run a subset; omit it to run all three
beta-gamma-light scenarios (S2-03, S3-01, S5-01).

### Summary Upsert

`/v1/summary/upsert` wraps an `ActionSummary` fixture in a request envelope:

```bash
python - <<'PY'
import json
from pathlib import Path

summary = json.loads(Path("tests/fixtures/photon/anvil_action_summary.json").read_text())
body = {
    "schema_version": "action-memory.v0.2",
    "request_id": "smoke-summary-upsert-001",
    "summary": summary,
}
Path("/tmp/photon-summary-upsert.json").write_text(json.dumps(body))
PY

curl -fsS \
  -H 'content-type: application/json' \
  -X POST \
  --data @/tmp/photon-summary-upsert.json \
  http://127.0.0.1:18765/v1/summary/upsert
```

Expected checks:

- `status` is `stored` for clean seeds (or `stored_with_warnings` if the
  answer-leak quality gate annotated the seed in `warn` mode).
- `summary_id` is `anvil-sum-photon-001`.

## Answer-leak Quality Gate

`POST /v1/summary/upsert` runs an answer-leak quality gate before
persisting any `ActionSummary` so seeds whose `facts[*]`, `next_hints[*]`,
or `avoid[*]` text pre-spoils the task answer can be rejected, annotated,
or just observed depending on the deployment mode.

| Variable | Values | Default |
|---|---|---|
| `PHOTON_QUALITY_GATE_MODE` | `strict` / `warn` / `observe` | `warn` |

- `strict`: any leak match returns `HTTP 422` with
  `{"detail": {"error": "answer_leak_detected", "summary_id": ..., "quality_warnings": [...]}}`
  and the seed is not persisted.
- `warn` (default): the seed is persisted with `quality_check_status =
  "warned"` and `quality_warnings` populated, and the response `status`
  is `stored_with_warnings`. Downstream retrieval applies a
  `quality_warned` attenuation factor so warned seeds rank below clean
  equivalents.
- `observe`: the seed is persisted unchanged; warnings are emitted to
  the operator log only. Use this mode to size impact before flipping to
  `warn` or `strict`.

Patterns currently guarded (see
`photon_action_memory/governance/answer_leak.py` for the SSOT):

| Pattern | Triggers on |
|---|---|
| `output_literal_json` | inline JSON object literal containing a `"key": value` pair |
| `output_key_enumeration` | "with keys / fields / columns X, Y, Z" (3+ identifiers enumerated as answer schema) |
| `direct_print_answer` | "prints / outputs / returns / shows a JSON object …" |
| `stdout_forecast` | "stdout will / contains / shows / is …" |
| `answer_assertion` | "the answer / result / output / response is …" |
| `numeric_answer_equality` | "`identifier = N`" / "`identifier equals N`" assertions |

The DB column `action_summaries.quality_check_status` is added by a
backwards-compatible migration; existing rows default to `"unchecked"`
so seeds that pre-date the gate keep their current admission behaviour.

## Focused Verification

Use these tests when changing the Anvil integration contract:

```bash
python -m pytest \
  tests/test_anvil_contract.py \
  tests/test_anvil_context_pack_api.py \
  tests/test_anvil_evaluate.py \
  tests/test_shared_fixtures.py \
  tests/test_rollout_policy.py \
  -q
```

Run full CI checks before merging shared behavior:

```bash
ruff format --check .
ruff check .
mypy photon_action_memory tests
pytest -q
python -m build
```
