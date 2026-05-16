# Issue #123 — Implementation Summary

## What Changed

- Added `photon_action_memory/models/checkpoint_builder.py`.
  - Builds scorer state from normalized feedback/eval records.
  - Writes a runtime checkpoint directory with manifest, state, weights, and
    integrity files.
- Added `scripts/build_action_memory_checkpoint.py`.
  - CLI wrapper for building a small local checkpoint from JSON records.
- Added tiny fixture checkpoint:
  - `tests/fixtures/photon/checkpoints/action_memory_tiny/manifest.json`
  - `state.json`
  - `weights.npz`
  - `integrity.json`
- Strengthened strict PHOTON scorer loading.
  - `PhotonMLXAdapter.from_checkpoint(..., strict=True)` now verifies
    checkpoint integrity before constructing the adapter.
  - `make_action_memory_scorer()` passes
    `PHOTON_ACTION_MEMORY_CHECKPOINT_STRICT` through and fails open on integrity
    errors.
- Added tests for builder, fixture validity, PHOTON scorer path, and strict
  fallback.
- Documented sidecar checkpoint env configuration and no-large-artifact policy.
- Added `workspace/v0.4.0/photon-checkpoint-scorer-eval.md` with a deterministic
  vs PHOTON fixture ranking comparison.

## Files

```text
photon_action_memory/models/checkpoint_builder.py
photon_action_memory/models/photon_adapter.py
photon_action_memory/models/photon_scorer.py
scripts/build_action_memory_checkpoint.py
tests/fixtures/photon/checkpoints/action_memory_tiny/
tests/test_action_memory_checkpoint_builder.py
tests/test_action_memory_scorer.py
docs/photon-action-memory.md
workspace/v0.4.0/photon-checkpoint-scorer-eval.md
```

## Notes

The committed checkpoint is intentionally tiny and CI-only. Production
checkpoints should be generated locally or stored in an external artifact
location, then referenced by `PHOTON_ACTION_MEMORY_CHECKPOINT`.
