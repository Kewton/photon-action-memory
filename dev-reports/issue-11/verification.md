# Issue 11 Verification

## Commands

- `python -m pytest tests/test_photon_adapter.py tests/test_sidecar_api.py tests/test_import.py -q`
  - Passed: `16 passed in 0.15s`
- `python -m ruff check photon_action_memory tests/test_photon_adapter.py`
  - Passed: `All checks passed!`
- `python -m mypy photon_action_memory`
  - Passed: `Success: no issues found in 25 source files`
- `python -m pytest -q`
  - Passed: `75 passed in 0.69s`

## Coverage Notes

- Default package import and default tests do not import MLX.
- Missing MLX is simulated through the adapter import seam to avoid loading the host MLX runtime.
- Invalid checkpoint configuration falls back to deterministic ranking and emits `model_unavailable`.
- Fake-MLX smoke scoring validates `score_actions`, `score_files`, `score_evidence`, and the
  sidecar reranking path.
