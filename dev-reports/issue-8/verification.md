# Issue #8 Verification

## Commands

- `pytest tests/test_datasets.py`
  - Initial run failed during import because the package was not installed on the active interpreter path.
- `PYTHONPATH=. pytest tests/test_datasets.py`
  - Passed: 7 tests.
- `PYTHONPATH=. ruff check photon_action_memory/training/datasets.py tests/test_datasets.py`
  - Passed after formatting fixes.
- `PYTHONPATH=. mypy photon_action_memory/training/datasets.py`
  - Passed.
- `PYTHONPATH=. pytest`
  - Passed: 56 tests.
- `PYTHONPATH=. ruff check .`
  - Passed.
- `PYTHONPATH=. mypy photon_action_memory`
  - Passed: 25 source files.

## Coverage

- Dataset records include `example_id`, `schema_version`, `source`, `task`, `state`, `label`, `quality`, and `redaction`.
- Deterministic train / val / test split is covered with stable input and reversed input order.
- JSONL round-trip preserves redaction report IDs.
- Stats cover action, tool, CLI command, target files, target-file totals, and redaction counters.
