# Issue #69 — Implementation Summary

## New files

### `photon_action_memory/eval/anvil_feedback.py`

- `EXCLUDED_QUALITY_STATUSES` — frozenset of statuses excluded from quality signal.
- `EvidenceFeedback` — per-evidence aggregate: `expansion_count`, `success_count`, `quality_score`.
- `PackFeedback` — pack-level aggregate: turn counts, adoption/success counts, `quality_score`, `evidence_feedback` dict.
- `aggregate_anvil_feedback(records)` — builds `PackFeedback` from `ContextPackEvalRecord` sequence, excluding fail-open/error turns.

### `photon_action_memory/ranking/feedback.py`

- `STALE_MAX_SCORE = 0.25` / `CONTRADICTED_MAX_SCORE = 0.15` / `MAX_QUALITY_BOOST = 0.2` — tunable constants.
- `apply_feedback_boost(base_score, status, quality_score)` — bounded boost with hard cap per status.
- `FeedbackAdjustedContextScorer` — wraps `FallbackContextScorer`, applies `PackFeedback` signals. Implements `ContextScorerProtocol`.

### `tests/fixtures/v0.2/anvil_evaluate_feedback.json`

Anvil evaluate fixture with 5 records: 2 adopted/success, 1 ignored/failure, 1 error (excluded), 1 shadow_not_injected (excluded). Used to test `aggregate_anvil_feedback` with the exclusion invariant.

### `tests/test_anvil_feedback.py`

43 tests covering all 6 acceptance criteria.

## Modified files

### `photon_action_memory/eval/__init__.py`

Added imports and `__all__` entries for `EXCLUDED_QUALITY_STATUSES`, `EvidenceFeedback`, `PackFeedback`, `aggregate_anvil_feedback`.

## Acceptance criteria mapping

| Criterion | Test(s) |
|---|---|
| Anvil evaluate fixture → aggregate feedback | `test_feedback_fixture_validates_and_aggregates`, `test_feedback_fixture_evidence_feedback` |
| `FallbackContextScorer` に feedback adjustment | `test_feedback_scorer_admission_boosts_valid_item`, `test_feedback_scorer_expansion_*`, `test_feedback_scorer_usefulness_*` |
| stale/contradicted は score で復活しない | `test_feedback_scorer_admission_stale_cannot_recover`, `test_feedback_scorer_admission_contradicted_cannot_recover`, `test_feedback_scorer_stale_scores_below_valid_always` |
| fail-open/error turn は quality signal から除外 | `test_error_turns_excluded_from_quality_turns`, `test_shadow_not_injected_excluded_from_quality_turns`, `test_not_available_excluded_from_quality_turns`, `test_all_excluded_turns_yields_zero_quality_score` |
| learned model なしで deterministic ranking 改善 | `test_feedback_improves_ranking_of_valid_over_stale`, `test_feedback_ranking_is_deterministic` |
| aggregate-safe feature が保存される | `test_pack_feedback_contains_only_aggregate_fields`, `test_evidence_feedback_contains_only_aggregate_fields` |
