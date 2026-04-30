# Issue 11 Implementation Summary

## Changed

- Added `models/state.py` scoring DTOs:
  - `PhotonScoringState`
  - `ActionCandidate`
  - `ScoredCandidate`
  - `ScoredFile`
  - `ScoredEvidence`
- Added runtime checkpoint manifest validation in `models/checkpoint.py`:
  - validates `photon-action-memory.mlx.v1` manifests;
  - reports missing and invalid checkpoints through typed exceptions;
  - drops unknown state keys by default and rejects them in strict mode.
- Replaced the adapter placeholder with `PhotonMLXAdapter`:
  - lazy-imports `mlx.core` only when a checkpoint path is configured;
  - exposes `score_actions`, `score_files`, and `score_evidence`;
  - supports tiny smoke scoring with manifest weights.
- Updated `/v1/suggest` to:
  - build the existing deterministic fallback candidate surface first;
  - optionally rerank it through the MLX adapter when `PHOTON_ACTION_MEMORY_CHECKPOINT` is set;
  - fall back to deterministic ranking when checkpoint or adapter setup fails.
- Updated the v0.1.0 preparation checklist for Issue #11 adapter/interface completion.
- Added focused adapter tests covering default import behavior, missing MLX simulation, checkpoint
  validation, invalid-checkpoint fallback, direct fake-MLX scoring, and sidecar fake-MLX scoring.

## Notes

The adapter does not introduce a real PHOTON model architecture. It creates the runtime-safe
boundary and smoke-testable scoring interface needed for the follow-up macOS MLX smoke issue.
