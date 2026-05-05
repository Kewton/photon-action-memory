# Design: ActionSummaryBuilder (Issue #35)

## Goal

Implement `ActionSummaryBuilder`, `SummaryCanonicalizer`, and `SummaryStateUpdater` in
`photon_action_memory/memory/summaries.py`.  All three operate on the v0.2 schema models
from `photon_action_memory.api.schema_v2`.

## Key Design Decisions

### 1. Deterministic-only fallback

No LLM call is made.  All claims are derived directly from `ActionChunk` fields using
the heuristics specified in `04_architecture.md` section 8.

### 2. Outcome -> category mapping

| chunk.outcome | Produces           | Does NOT produce |
|---------------|--------------------|-----------------|
| `useful`      | Fact (with evidence_ids) | Hypothesis, FailedAttempt |
| `partial`     | Hypothesis (open)  | Fact, FailedAttempt |
| `failed`      | FailedAttempt      | Fact, Hypothesis |
| `irrelevant`  | AvoidGuidance      | Fact, Hypothesis, FailedAttempt |
| `unknown`     | (nothing extra)    | Fact, Hypothesis, FailedAttempt |

`actions_done` is always populated regardless of outcome.

### 3. Evidence grounding invariant

Facts are emitted only when `chunk.event_ids` is non-empty.  The `SummaryCanonicalizer`
enforces this post-hoc by stripping any `Fact` without `evidence_ids` and downgrading
`validity` to `"partial"`.

### 4. Hypotheses stay separate from facts

`Hypothesis` objects are never added to `facts` and vice versa.  Both carry a `status`
field (`"open"` for newly created hypotheses).

### 5. Incremental update: `S_t = update(S_{t-1}, ActionChunk_t)`

`SummaryStateUpdater.update()` calls `ActionSummaryBuilder` to produce a chunk-level
summary, canonicalizes it, then merges fields into the previous state:

- `source_chunk_ids` - append new chunk_id
- `actions_done` - concatenate all (no deduplication; each action is distinct)
- `facts`, `hypotheses` - deduplicated by `.text` (same observation seen twice -> kept once)
- `failed_attempts` - deduplicated by `.action` key
- `avoid` - deduplicated by `.action` key
- `next_hints` - replaced by the new chunk's hints (more recent is more relevant)
- `token_cost` - summed

### 6. Token cost estimation

A heuristic of 200 raw tokens per event is used when actual event storage is unavailable.
`max(summary_tokens, events * 200)` ensures `tokens_saved_vs_raw >= 0`.

### 7. Type-safe merge helper

`_merge_by_text` uses a `TypeVar` bound to a `_HasText` Protocol to work for both
`list[Fact]` and `list[Hypothesis]` without `type: ignore` or dynamic casting.
