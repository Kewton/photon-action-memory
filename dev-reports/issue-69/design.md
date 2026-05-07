# Issue #69 — Design Note

## Objective

Apply Anvil evaluate log data to the PHOTON Context Firewall scoring system.
Derive quality signals from `ContextPackEvalRecord` sequences and use them to
boost `FallbackContextScorer` scores, while guaranteeing that stale/contradicted
items cannot recover to valid-item score ranges.

## Approach

Two new modules:

```
ContextPackEvalRecord (from /v1/evaluate logs)
    ↓
aggregate_anvil_feedback()   [eval/anvil_feedback.py]
    → PackFeedback (aggregate counts + rates, no raw content)
    → EvidenceFeedback (per-evidence expansion × outcome correlation)
         ↓
FeedbackAdjustedContextScorer.score_*()  [ranking/feedback.py]
    → boosted AdmissionScore / EvidenceExpansionScore / SummaryUsefulnessScore
    → unchanged StalenessRiskScore (never adjusted)
```

### `eval/anvil_feedback.py`

Aggregates `ContextPackEvalRecord` sequences into `PackFeedback`.

**Excluded statuses** (`EXCLUDED_QUALITY_STATUSES`): `error`, `not_available`,
`shadow_not_injected`. These records are counted in `total_turns` but excluded
from `quality_turns` and `quality_score` to prevent infrastructure noise from
diluting the quality signal.

`quality_score = success_count / quality_turns` where success outcomes are
`{success, accepted, completed}`.

Per-evidence `EvidenceFeedback` is derived from which `evidence_ids_expanded`
correlated with success outcomes across quality turns.

`PackFeedback` stores only aggregate counts and rates — no raw prompts, tool
outputs, or user text — making it safe to persist for future model training.

### `ranking/feedback.py`

Provides `apply_feedback_boost(base_score, status, quality_score)` and
`FeedbackAdjustedContextScorer`.

**Hard caps** (enforced regardless of feedback magnitude):

| Status | Max score |
|---|---|
| `stale` | 0.25 |
| `contradicted` | 0.15 |
| `unsafe` | 0.15 |
| others | 1.0 (no cap) |

The 0.25 cap for stale sits above the natural deterministic max for stale items
(≈ 0.20) but well below feedback-boosted valid items, so the ranking order is
preserved.

**Staleness risk**: `score_staleness_risk` delegates entirely to
`FallbackContextScorer` with no feedback adjustment. Stale always stays stale.

**Evidence expansion**: uses per-evidence `quality_score` when the evidence ID
has been seen before; falls back to the pack-level `quality_score` for unseen IDs.

## Key invariants

1. stale/contradicted/unsafe items never exceed their hard cap, even at maximum feedback.
2. Staleness risk scores are not modified by any feedback signal.
3. `PackFeedback` / `EvidenceFeedback` contain only aggregate-safe features.
4. fail-open/error/not_available/shadow_not_injected turns are excluded from quality_score.
5. `FeedbackAdjustedContextScorer` satisfies `ContextScorerProtocol` and is injectable.
