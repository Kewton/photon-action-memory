# Issue #45 — PHOTON Context Scorer Interfaces

## What was added

### `photon_action_memory/models/context_scorer.py`

New module providing the Context Firewall scoring layer so PHOTON can plug into
the four admission-pipeline decisions:

| Dimension | Scorer method | Returns |
|-----------|--------------|---------|
| Context admission priority | `score_admission` | `list[AdmissionScore]` |
| Evidence expansion priority | `score_evidence_expansion` | `list[EvidenceExpansionScore]` |
| Summary usefulness for task | `score_summary_usefulness` | `list[SummaryUsefulnessScore]` |
| Staleness risk | `score_staleness_risk` | `list[StalenessRiskScore]` |

#### Public types

- **Score result dataclasses** — `AdmissionScore`, `EvidenceExpansionScore`,
  `SummaryUsefulnessScore`, `StalenessRiskScore` — each frozen, carrying
  `item_id`, `score`/`risk` (float in [0,1]), and `reason` string.
- **`ScoringEvent`** — frozen dataclass emitted to the optional eval hook after
  each scored item.  Fields: `scorer_kind`, `item_id`, `score`, `reason`.
- **`ContextScorerHook`** — type alias `Callable[[ScoringEvent], None]`; passed
  to `FallbackContextScorer(eval_hook=...)`.
- **`ContextScorerProtocol`** — `@runtime_checkable Protocol` defining the four
  scoring methods.  Any class exposing these methods satisfies it.
- **`FallbackContextScorer`** — deterministic implementation requiring no model.

#### FallbackContextScorer scoring logic

**Admission** (`score_admission`):
- Weighted richness: `facts×3 + hypotheses×2 + failed_attempts + avoid`
- Normalised by ceiling of 12, then multiplied by a validity factor
  (`valid=1.0`, `partial=0.7`, `unknown=0.5`, `stale=0.2`, `contradicted=0.1`).
- Empty summaries (richness=0) always score 0.0.

**Evidence expansion** (`score_evidence_expansion`):
- Base score from `expand_policy` (`always=0.9`, `on_demand_only=0.5`, `deny=0.0`).
- `deny` short-circuits to 0.0.  Otherwise penalised by staleness risk×0.5.

**Summary usefulness** (`score_summary_usefulness`):
- Task-text word overlap (70 %) + content richness (30 %).
- Falls back to half-richness score when `task_text` is empty.

**Staleness risk** (`score_staleness_risk`):
- Direct table lookup: `valid→0.0`, `partial→0.3`, `unknown→0.5`,
  `stale→0.8`, `contradicted→1.0`; unknown status defaults to 0.5.

#### Eval comparison hooks

Passing `eval_hook=fn` to `FallbackContextScorer` causes `fn(ScoringEvent(…))`
to be called after every scored item.  Callers can aggregate these events into
`ComparisonRecord` fields (e.g. `total_summaries_evaluated`) for the eval
comparison framework in `eval/comparison.py`.

#### MLX-free guarantee

The module imports only:
- `collections.abc.{Callable,Sequence}`
- `dataclasses.dataclass`
- `typing.{Protocol,runtime_checkable}`
- `photon_action_memory.api.schema_v2.{ActionSummary,EvidenceRef}`

`mlx.core` is never imported at module level or by the fallback scorer.

### `tests/test_context_scorer.py`

40 smoke tests grouped by scorer dimension:

- **Admission** (9 tests) — empty input, no-content zero score, positive score,
  stale < valid, contradicted < stale, clamp to [0,1], determinism, ID
  preservation, correct list length.
- **Evidence expansion** (6 tests) — deny=0, always>0.5, on_demand mid range,
  stale penalty, ID preservation, empty list.
- **Summary usefulness** (5 tests) — empty list, low score with no task text,
  matching task text raises score, no-overlap fallback, determinism.
- **Staleness risk** (7 tests) — empty list, valid=0.0, contradicted=1.0,
  stale>0.5, partial ordering, unknown mid-range, ID preservation.
- **Eval hook** (8 tests) — hook called per item, correct `scorer_kind` for all
  four dimensions, event carries item_id + score, no-hook does not raise, hook
  not called for empty input.
- **Injectable scorer / Protocol** (5 tests) — `FallbackContextScorer`
  satisfies protocol, `_FixedScorer` satisfies protocol, fixed scores returned,
  callable through Protocol-typed parameter.
