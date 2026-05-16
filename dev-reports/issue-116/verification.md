# Issue #116 Verification

## Focused tests

```
$ python -m pytest tests/test_anvil_feedback.py -x -q
................................................                         [100%]
48 passed in 0.12s
```

All 48 cases (43 pre-existing + 5 new) pass.

## Full test suite

Shared contracts touched: `PackFeedback` gained three required fields
and `apply_feedback_boost` gained two keyword-only arguments. Ran the
whole suite to confirm no dependent broke.

```
$ python -m pytest tests/ -x -q
... (omitted) ...
1001 passed, 1 skipped, 2 warnings in 12.55s
```

The single skip is the opt-in MLX smoke test, unchanged by this work.

## Lint and type checks

```
$ python -m ruff check photon_action_memory/eval/anvil_feedback.py \
    photon_action_memory/ranking/feedback.py tests/test_anvil_feedback.py
All checks passed!

$ python -m mypy photon_action_memory/eval/anvil_feedback.py \
    photon_action_memory/ranking/feedback.py
Success: no issues found in 2 source files
```

## Manual sanity check

The new logic is fully exercised by tests; no manual REPL probe was
needed beyond the cases captured in `test_anvil_feedback.py`.

## Acceptance criteria

- [x] `_SUCCESS_OUTCOMES` に `user_positive` / `user_rule` 追加
- [x] `user_correction` を新 const `_CORRECTION_OUTCOMES` で表現し、
      `aggregate_anvil_feedback` で別カウント
      (`PackFeedback.correction_count`)
- [x] `aggregate_anvil_feedback` の docstring 更新（user_* outcome の
      semantics 明記）
- [x] regression test `tests/test_anvil_feedback.py` に user_* outcome
      ケース追加 (4 種: user_positive / user_rule / user_correction /
      user_negative)
- [x] 任意項目: `user_positive` を通常 success より強い weight で
      集計できるよう `FeedbackAdjustedContextScorer` の boost 計算に
      user-vs-implicit signal 重み分離を導入
      (`MAX_USER_SIGNAL_BOOST`, `user_signal_score`)
