# Issue #110 Verification

## Focused

```
$ python -m pytest tests/test_contradiction_detection.py tests/test_contradiction_detection_api.py -v
23 passed in 0.28s
```

Covers:

- 14 syntax-based detection cases (happy paths, false-positive guards,
  edge cases including empty input, single summary, scope filtering,
  Japanese negation, dedup).
- API audit endpoint pair detection.
- Context-pack `contradiction_detected` warning emission.
- `validity.status="contradicted"` removes the warning (seed is no
  longer retrieved).
- `validity.status="needs_review"` keeps the warning (seed is still
  retrieved and surfaced for review).
- `photon-audit detect-contradictions` payload builder.

## Broad

```
$ python -m pytest -q
996 passed, 1 skipped, 2 warnings in 20.35s
```

Skipped test is the opt-in MLX integration smoke that runs only on the
dedicated macOS workflow; unrelated to this change.

## Manual checks

- `photon_action_memory.governance.contradiction` imports cleanly under
  Python 3.12.
- `photon-audit detect-contradictions --help` exposes the new
  subcommand once the project is reinstalled (the script entry was
  registered via `pyproject.toml`).
