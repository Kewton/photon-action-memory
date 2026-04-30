# Issue #12 Design: Checkpoint load interface

## Goal

Add a runtime-only checkpoint boundary that the optional PHOTON adapter can use
without importing training modules or requiring MLX on the default import path.

## Shape

- Keep `photon_action_memory.models.checkpoint` pure stdlib.
- Use `CheckpointState` as the runtime DTO for `state.json`, mirroring the
  reference training state fields that are safe for runtime consumers.
- Load only `state.json` and verify `integrity.json` hashes for `state.json`
  and `weights.npz`; actual MLX weight materialization remains adapter work.
- Treat missing `integrity.json` as a warning by default and an error in strict
  mode.
- Treat hash mismatches, malformed JSON, and non-object state as invalid
  checkpoints.
- Drop unknown state keys with a warning so newer checkpoint writers remain
  forward compatible with older runtimes.

## Adapter Boundary

`photon_adapter` gets a small availability probe that attempts to load a
configured checkpoint state and returns unavailable on missing or invalid
checkpoints. The API server already falls back to deterministic ranking when
`is_model_available()` is false, so this keeps fail-open behavior in one place.

## Tests

Add focused checkpoint tests for:

- import boundary does not import training modules or MLX;
- valid state load and integrity verification;
- missing integrity warning vs strict error;
- hash mismatch rejection;
- unknown state key warning/drop;
- adapter fallback when checkpoint is missing or invalid.
