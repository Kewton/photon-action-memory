# Issue #109 Verification

## Automated Checks

- `python -m pytest tests/test_context_pack.py tests/test_anvil_eval_multilingual_seeds.py -q`
  - Result: `118 passed`
- `python -m pytest -q`
  - Result: `955 passed, 1 skipped, 2 warnings`
- `python -m ruff check photon_action_memory/api/server.py photon_action_memory/memory/retrieval.py tests/test_context_pack.py tests/test_anvil_eval_multilingual_seeds.py`
  - Result: pass
- `python -m ruff format --check photon_action_memory/api/server.py photon_action_memory/memory/retrieval.py tests/test_context_pack.py tests/test_anvil_eval_multilingual_seeds.py`
  - Result: pass
- `python -m mypy photon_action_memory/api/server.py photon_action_memory/memory/retrieval.py tests/test_context_pack.py tests/test_anvil_eval_multilingual_seeds.py`
  - Result: pass
- `python -m ruff check .`
  - Result: pass
- `python -m ruff format --check .`
  - Result: pass
- `python -m mypy photon_action_memory tests`
  - Result: pass
- `bash -n scripts/seed_common_seeds.sh`
  - Result: pass

## Notes

The full Anvil A-1/A-0 differential eval was not run in this repository
worktree; the photon-side retrieval, dedup, and token-budget behavior are
covered by automated tests.
