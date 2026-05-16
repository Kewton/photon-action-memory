# Issue #116 Implementation Summary

## Changes

### `photon_action_memory/eval/anvil_feedback.py`

- Extended `_SUCCESS_OUTCOMES` with `user_positive` and `user_rule`. Both
  are explicit-user-feedback outcomes introduced by Anvil PR #599 that
  semantically indicate user acceptance and therefore belong in the
  success allowlist.
- Added `_USER_POSITIVE_OUTCOMES = frozenset({"user_positive",
  "user_rule"})` — the subset of `_SUCCESS_OUTCOMES` sourced from explicit
  user feedback, tracked separately so the firewall can weight it more
  heavily.
- Added `_CORRECTION_OUTCOMES = frozenset({"user_correction"})`. A
  correction is a quality engagement signal but the underlying action was
  wrong, so it must not inflate `success_count` or `quality_score`.
- Extended `PackFeedback` with `correction_count: int`,
  `user_positive_count: int`, and `user_signal_score: float`. The
  existing `success_count` / `quality_score` fields now naturally include
  the user-positive / user-rule additions because of the allowlist
  change.
- Updated `aggregate_anvil_feedback` to populate the new fields and
  documented the full outcome taxonomy (implicit success, user_positive,
  user_rule, user_correction, plus the catch-all non-success bucket
  including `user_negative`).

### `photon_action_memory/ranking/feedback.py`

- Added `MAX_USER_SIGNAL_BOOST = 0.1` (combined max boost remains 0.30,
  still within the `[0,1]` clamp and the per-status hard caps).
- `apply_feedback_boost` gained `user_signal` and `max_user_boost`
  keyword arguments. The user-signal boost layers additively on top of
  the existing quality-score boost.
- `FeedbackAdjustedContextScorer` passes
  `user_signal=self._feedback.user_signal_score` through every scoring
  method (admission, evidence expansion, summary usefulness). Staleness
  risk remains unadjusted.
- Reason strings extended with `user_signal={…:.2f}` so the eval hook
  surfaces the new dimension.

### `tests/test_anvil_feedback.py`

Added five regression cases:

1. `test_user_positive_counted_as_success` — user_positive flips success
   and user-signal counters.
2. `test_user_rule_counted_as_success` — same shape for user_rule.
3. `test_user_correction_counted_as_correction_not_success` —
   user_correction increments only `correction_count`.
4. `test_user_negative_not_counted_as_success` — confirms the negative
   thumbs-down outcome stays a non-success quality turn.
5. `test_user_signal_score_boosts_scoring_above_implicit_success` —
   demonstrates the boost path: two packs with identical
   `quality_score=1.0` but different `user_signal_score` rank the
   explicit-user-positive pack strictly higher, bounded by
   `MAX_USER_SIGNAL_BOOST`.

## What was *not* changed

- The `_SUCCESS_OUTCOMES` constants in `eval/context_pack_log.py`,
  `eval/summary_feedback.py`, and `eval/comparison.py` were left
  unchanged. The Issue acceptance criteria scope the allowlist extension
  to `anvil_feedback.py`. A follow-up Issue can unify the four constants
  once production observation confirms the user-explicit signal volume.
- No API schema changes were necessary because
  `ContextPackEvalEvent.outcome` is already `str | None`.

## Backwards compatibility

`PackFeedback` gained three required fields. Direct constructor callers
would break, but a repo-wide grep confirmed the only constructor sites
are `aggregate_anvil_feedback` (updated) and the test fixture builders
(use the aggregator, no direct construction). The new
`apply_feedback_boost` argument is keyword-only with a default of `0.0`,
so existing callers retain their previous behaviour.
