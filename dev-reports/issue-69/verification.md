# Issue #69 — Verification

## Test run

```
python -m pytest tests/test_anvil_feedback.py -v
```

Result: **43 passed** in 0.09 s.

## Broad regression check

```
python -m pytest --tb=short -q
```

Result: **698 passed, 1 skipped** in 2.03 s.
(Skipped: MLX smoke — opt-in on macOS workflow only.)

## Acceptance criteria verification

| Criterion | Status |
|---|---|
| Anvil evaluate fixture → aggregate feedback | PASS — `test_feedback_fixture_validates_and_aggregates` reads `anvil_evaluate_feedback.json`, asserts total_turns=5, quality_turns=3, quality_score≈0.667 |
| `FallbackContextScorer` に feedback adjustment | PASS — boosted scores exceed base for valid items (admission, expansion, usefulness) |
| stale/contradicted は score で復活しない | PASS — rich stale ≤ 0.25, rich contradicted ≤ 0.15 even at quality_score=1.0 |
| fail-open/error turn は quality signal から除外 | PASS — error/shadow_not_injected/not_available excluded from quality_turns |
| learned model なしで deterministic ranking 改善 | PASS — `test_feedback_improves_ranking_of_valid_over_stale`, `test_feedback_ranking_is_deterministic` |
| aggregate-safe feature が保存される | PASS — `PackFeedback`/`EvidenceFeedback` contain only counts and rates, no raw content fields |
