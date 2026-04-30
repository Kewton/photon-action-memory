# Issue #13 Design

## Goal

Add a separate macOS-only MLX smoke workflow so optional MLX dependency coverage is available without making the standard Ubuntu CI require MLX.

## Scope

- Add `.github/workflows/mlx-smoke.yml` with `workflow_dispatch`, nightly schedule, and `develop` push triggers.
- Add `tests/integration/test_mlx_smoke.py` as a focused import and tiny scoring smoke.
- Keep the smoke safe for normal `pytest` runs by requiring explicit workflow opt-in before importing `mlx.core`.
- Update planning docs only where they should reflect that the workflow now exists.

## Verification Plan

- Run the new smoke test locally and confirm it skips without MLX on non-MLX environments.
- Run standard test suite to confirm Ubuntu-style dev install still does not require MLX.
- Run lint/format/type checks because workflow and tests are CI-facing.
