# Issue #107 Verification

## Automated Checks

- `python -m pytest tests/test_context_pack.py tests/test_overlap_detector.py -q`
  - Result: `61 passed, 2 warnings`
- `python -m pytest tests/test_anvil_eval_multilingual_seeds.py -q`
  - Result: `59 passed`
- `python -m pytest tests/test_context_pack.py tests/test_overlap_detector.py tests/test_anvil_eval_multilingual_seeds.py -q`
  - Result: `120 passed, 2 warnings`
- `python -m pytest -q`
  - Result: `947 passed, 1 skipped, 2 warnings`
- `python -m ruff format --check photon_action_memory/context/render.py photon_action_memory/context/admission.py photon_action_memory/context/quality_gate.py photon_action_memory/context/pack.py tests/test_context_pack.py`
  - Result: pass
- `python -m ruff check photon_action_memory/context/render.py photon_action_memory/context/admission.py photon_action_memory/context/quality_gate.py photon_action_memory/context/pack.py tests/test_context_pack.py`
  - Result: pass
- `python -m ruff format --check .`
  - Result: pass
- `python -m ruff check .`
  - Result: pass
- `python -m mypy photon_action_memory/context tests/test_context_pack.py`
  - Result: pass
- `python -m mypy photon_action_memory tests`
  - Result: pass

## Notes

The full Anvil cross-lingual eval target from the issue was not run in this
repository worktree. The photon-side regression coverage verifies that
S2-style premature-risk seeds are admitted with facts preserved and risky
`next_hints` removed from prompt-visible text.
