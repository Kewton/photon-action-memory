# Issue 6 Verification

## Commands

- `python -m pytest tests/test_ranking_fallback.py tests/test_sidecar_api.py -q`
  - Result: pass, 11 tests.
- `python -m pytest -q`
  - Result: pass, 55 tests.
- `ruff format --check .`
  - Result: pass, 35 files already formatted.
- `ruff check .`
  - Result: pass.
- `mypy photon_action_memory tests`
  - Result: pass, no issues.
- `python -m build`
  - Result: pass after allowing network access for isolated `hatchling` build dependency installation.

## Coverage

- Same input returns the same ordered response.
- Recent error file path is ranked first as an `inspect` suggestion.
- Top-k suggestion limit is enforced.
- Evidence summaries stay within the evidence character budget.
- Repeated read/search actions emit `repeat_failure` warnings.
- Edit-like requests without evidence emit `missing_evidence`.
- Destructive shell commands are detected and are not emitted as suggestions.
