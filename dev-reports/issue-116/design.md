# Issue #116 Design — Extend `_SUCCESS_OUTCOMES` with explicit user feedback

## Goal

Anvil PR #599 (Issue #592) introduced four explicit-user-feedback outcome
values that are emitted via `POST /v1/evaluate`'s `outcome` field:

| outcome value     | semantics                                         |
| ----------------- | ------------------------------------------------- |
| `user_positive`   | user explicitly approved the action (thumbs up).  |
| `user_rule`       | user converted the suggestion into a stored rule. |
| `user_correction` | user accepted the result but corrected it.        |
| `user_negative`   | user explicitly rejected the action (thumbs down).|

`photon_action_memory/eval/anvil_feedback.py` currently only treats
`success` / `accepted` / `completed` as success, so the four explicit
signals collapse into "failure" and never reach the
`FeedbackAdjustedContextScorer` boost path. This deflates `quality_score`
and starves the per-evidence quality signal that drives the firewall.

## Scope

In:

- `_SUCCESS_OUTCOMES` in `anvil_feedback.py` gains `user_positive` and
  `user_rule` so they count as quality successes alongside implicit
  successes.
- New `_CORRECTION_OUTCOMES = frozenset({"user_correction"})` plus a new
  `correction_count` field on `PackFeedback`. Corrections are a quality
  turn (the user engaged) but **not** a success, so they count toward
  `quality_turns` but neither `success_count` nor `correction_count`
  inflate `quality_score`.
- `aggregate_anvil_feedback` docstring updated with explicit-feedback
  semantics.
- 4 regression tests in `tests/test_anvil_feedback.py` covering
  `user_positive`, `user_rule`, `user_correction`, `user_negative`.
- `FeedbackAdjustedContextScorer` (`ranking/feedback.py`) learns a
  separate user-signal boost: explicit `user_positive` / `user_rule`
  turns add a stronger boost than implicit successes. Implemented as a
  new `user_signal_score` field on `PackFeedback` plus a
  `MAX_USER_SIGNAL_BOOST` constant added on top of the existing
  quality-score boost. The hard caps on stale/contradicted/unsafe are
  unchanged.

Out:

- The other modules with their own `_SUCCESS_OUTCOMES` constant
  (`eval/context_pack_log.py`, `eval/comparison.py`,
  `eval/summary_feedback.py`) are not touched in this Issue. Their
  reports remain implicit-success-only; a follow-up Issue can unify them
  once the user-explicit signal has been observed in production.
- No schema changes — `ContextPackEvalEvent.outcome` is already
  `str | None`, so the four new strings flow through without validation
  changes.
- `user_correction` is *not* added to `_SUCCESS_OUTCOMES`. A correction
  is a quality engagement signal but ultimately the original action was
  wrong; merging it into success would mask regressions.
- Per-evidence quality scoring continues to treat success and
  correction identically to the existing fail-open rules: only
  `_SUCCESS_OUTCOMES` membership flips an evidence expansion to a
  positive sample. Corrections do not flip the bit.

## Data shape

```python
@dataclass(frozen=True)
class PackFeedback:
    total_turns: int
    quality_turns: int
    adoption_count: int
    success_count: int
    correction_count: int      # NEW — outcome in _CORRECTION_OUTCOMES
    user_positive_count: int   # NEW — outcome in _USER_POSITIVE_OUTCOMES
    quality_score: float
    user_signal_score: float   # NEW — user_positive_count / quality_turns
    evidence_feedback: dict[str, EvidenceFeedback]
```

- `quality_score` keeps its existing meaning:
  `success_count / quality_turns`. `success_count` now includes
  `user_positive` and `user_rule` per the allowlist extension.
- `user_signal_score` is a separate ratio so the boost path can weight
  explicit feedback differently from implicit success.
- `correction_count` is reported but does not contribute to either
  ratio.

## Boost weighting

`apply_feedback_boost(base, status, quality_score, *, user_signal=0.0)`
adds `quality_score * MAX_QUALITY_BOOST + user_signal *
MAX_USER_SIGNAL_BOOST`, then clamps and applies the existing hard cap.

Defaults: `MAX_QUALITY_BOOST = 0.20` (unchanged),
`MAX_USER_SIGNAL_BOOST = 0.10`. Combined max boost is 0.30; the
combined value is still clamped to `[0,1]` and to the per-status hard
cap, so the safety invariants on stale/contradicted/unsafe items are
preserved.

`FeedbackAdjustedContextScorer` passes
`user_signal=self._feedback.user_signal_score` into every
`apply_feedback_boost` call.

## Tests

New cases in `tests/test_anvil_feedback.py`:

1. `test_user_positive_counted_as_success` — single
   `_record("adopted", "user_positive")` yields
   `success_count == 1`, `quality_score == 1.0`,
   `user_positive_count == 1`, `user_signal_score == 1.0`.
2. `test_user_rule_counted_as_success` — same shape with
   `outcome="user_rule"`.
3. `test_user_correction_counted_as_correction_not_success` — single
   `_record("adopted", "user_correction")` yields
   `success_count == 0`, `correction_count == 1`,
   `quality_score == 0.0`.
4. `test_user_negative_not_counted_as_success` — single
   `_record("adopted", "user_negative")` yields
   `success_count == 0`, `correction_count == 0`,
   `quality_score == 0.0` (i.e. the existing failure semantics).

Existing tests stay untouched. `PackFeedback` gains fields but no
existing field is renamed or removed.

One extra test on the boost path:
`test_user_signal_score_boosts_scoring` confirms that two packs with
identical `quality_score` but different `user_signal_score` rank the
explicit-user-positive pack higher.

## File map

- `photon_action_memory/eval/anvil_feedback.py` — extend
  `_SUCCESS_OUTCOMES`, add `_USER_POSITIVE_OUTCOMES`,
  `_CORRECTION_OUTCOMES`, extend `PackFeedback` and
  `aggregate_anvil_feedback`, update docstring.
- `photon_action_memory/ranking/feedback.py` — add
  `MAX_USER_SIGNAL_BOOST`, extend `apply_feedback_boost` signature with
  `user_signal`, wire `user_signal_score` through every scorer method.
- `tests/test_anvil_feedback.py` — 4 user_* regression cases + 1 boost
  weighting case.
