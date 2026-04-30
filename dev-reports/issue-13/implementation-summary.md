# Issue #13 Implementation Summary

## Changes

- Added `.github/workflows/mlx-smoke.yml` for a macOS-only MLX smoke job.
- Configured the workflow for `workflow_dispatch`, nightly schedule, and `develop` push.
- Added `tests/integration/test_mlx_smoke.py` with an explicit `PHOTON_RUN_MLX_SMOKE=1` opt-in before importing MLX.
- Kept the runtime PHOTON adapter fail-closed; MLX importability alone is not treated as an available PHOTON model.
- Updated v0.1.0 planning docs to describe the separated MLX smoke gate and tiny scoring smoke.

## Notes

The smoke test is collected by normal pytest but skips unless the dedicated workflow opt-in is set. This prevents standard Ubuntu CI and local dev runs from importing or requiring MLX.
