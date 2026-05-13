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

- `status` is `stored`.
- `summary_id` is `anvil-sum-photon-001`.

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

