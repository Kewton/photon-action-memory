# Issue #123 — Verification

## Focused Tests

```bash
python -m pytest \
  tests/test_action_memory_checkpoint_builder.py \
  tests/test_action_memory_scorer.py \
  tests/test_photon_adapter.py \
  tests/test_checkpoint.py \
  -q
```

Result:

```text
28 passed
```

## Type Check

```bash
python -m mypy photon_action_memory \
  tests/test_action_memory_checkpoint_builder.py \
  tests/test_action_memory_scorer.py \
  tests/test_photon_adapter.py \
  tests/test_checkpoint.py
```

Result:

```text
Success: no issues found in 66 source files
```

## Lint / Format

```bash
python -m ruff check .
```

Result:

```text
All checks passed!
```

```bash
python -m ruff format --check .
```

Result:

```text
120 files already formatted
```

## CLI Smoke

```bash
python scripts/build_action_memory_checkpoint.py \
  /tmp/action_memory_checkpoint_records.json \
  --output /tmp/action-memory-checkpoint-smoke \
  --model-version action-memory-smoke-v1
```

Result:

```text
checkpoint manifest/state/weights/integrity paths printed successfully
```

## Acceptance Criteria

| Criterion | Status |
|---|---|
| checkpoint creation implemented or documented | Done: builder module, CLI, docs |
| tiny fixture checkpoint without network/model download | Done |
| valid checkpoint enters `PhotonMLXActionMemoryScorer` path | Done: scorer test with fake MLX |
| missing/broken/MLX-unavailable fallback | Done: existing + new tests |
| strict integrity check tested | Done |
| deterministic vs PHOTON ranking report | Done |
| no large checkpoint policy documented | Done |
| sidecar env example documented | Done |
