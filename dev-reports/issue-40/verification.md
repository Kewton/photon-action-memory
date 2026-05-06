# Issue #40 - StalenessGuard: Verification

## Commands Run

```
python -m ruff format --check .
python -m ruff check .
python -m mypy photon_action_memory tests
python -m pytest -q
```

## Results

### ruff format

```
61 files already formatted
```

Exit code: 0 - PASS

### ruff check

```
All checks passed!
```

Exit code: 0 - PASS

### mypy

```
Success: no issues found in 59 source files
```

Exit code: 0 - PASS

### pytest

```
443 passed, 1 skipped in 1.20s
```

1 skipped test: `tests/integration/test_mlx_smoke.py` - opt-in MLX smoke test, not relevant to this change.

Exit code: 0 - PASS

## New Tests Added

`tests/test_staleness.py` - 47 new tests, all passing:

| Group | Count | Coverage |
|---|---|---|
| FileFingerprinter | 6 | determinism, hex format, line-range keys |
| Commit hash trigger | 3 | changed, unchanged, skip when None |
| Branch trigger | 3 | changed, unchanged, skip when not provided |
| Task signature trigger | 2 | changed, unchanged |
| File fingerprint trigger | 4 | changed, unchanged, missing, skip when None |
| Line range trigger | 2 | changed, missing |
| Contradiction trigger | 3 | matching fact, matching hypothesis, unrelated |
| Valid case | 2 | all-same context, empty context |
| apply() | 3 | stale, non-mutation, valid |
| Integration (pack) | 5 | omit via guard, mixed pack, omitted reason, decision reason, contradicted reason |
| Prompt-safety | 4 | no raw content, truncated commits, branch name safe |

## Regression Checks

All 396 pre-existing tests on the rebased develop branch continue to pass. The only change to existing code is `admission.py` line 39-42 (include `validity.reason` in the omit reason). This is backward-compatible: when `validity.reason` is `None` (the common case in existing tests), the behavior is identical to before.
