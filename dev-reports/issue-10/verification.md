# Issue #10 Verification

## Commands

- `python -m pytest tests/test_schema.py -q`
  - Pass: `10 passed`
- `python -m ruff format --check .`
  - Pass: `34 files already formatted`
- `python -m ruff check .`
  - Pass: `All checks passed!`
- `python -m mypy photon_action_memory tests`
  - Pass: `Success: no issues found in 32 source files`
- `python -m pytest -q`
  - Pass: `50 passed`
- `python -m build`
  - Pass: built sdist and wheel after allowing network access for isolated build dependency installation.

## Fixture Coverage

- `SuggestRequest` validates the Anvil shadow-mode request fixture.
- `SuggestResponse` validates stable suggestion ids and response metadata.
- `EventRequest` validates a `shadow_evaluation` event-store payload.
- `EvaluationRequest` validates adoption and ignored records with request id, suggestion ids, actual next action, matched, ignored reason, outcome, latency, and sidecar status.

## Notes

An initial sandboxed `python -m build` attempt failed because the isolated build environment could not resolve/download `hatchling>=1.25`. The rerun with network approval passed.
