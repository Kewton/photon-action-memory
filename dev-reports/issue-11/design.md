# Issue 11 Design: Optional PHOTON MLX Adapter

## Goal

Add an optional PHOTON / MLX scoring boundary without making MLX a normal import-time
dependency. The default sidecar path must continue to work in environments that do not
install the `mlx` extra.

## Design

- Keep `photon_action_memory.models.photon_adapter` importable without MLX by lazy-importing
  `mlx.core` only when a configured checkpoint is used.
- Add model-independent scoring DTOs in `models/state.py` so later smoke and integration tests
  can exercise `score_actions`, `score_files`, and `score_evidence` without depending on the
  API schema internals.
- Add a small runtime checkpoint manifest loader in `models/checkpoint.py`:
  - missing paths raise a typed unavailable error;
  - malformed JSON or schema mismatches raise a typed invalid error;
  - unknown state keys are dropped and returned as warnings.
- Route `/v1/suggest` through the adapter only when `PHOTON_ACTION_MEMORY_CHECKPOINT` is set and
  a valid MLX runtime/checkpoint is available. Any adapter initialization or scoring failure
  returns the existing deterministic fallback ranking and fallback model version.

## Scope Notes

This issue creates the optional scoring interface and fail-closed boundary. It does not implement
real PHOTON model inference weights; the adapter produces stable heuristic scores over the same
candidate surface so a later macOS MLX smoke issue can validate the runtime path.
