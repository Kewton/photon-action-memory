# Issue #87 — Design Note

## Objective

`/v1/evaluate` の adoption outcome を summary 単位で集計し、effective summary を
boost / 悪化 summary を demote または disable できるようにする。固定 seed では
なく、実行結果から summary の信頼度を更新する。

## Approach

```
/v1/evaluate  (ContextPackEvalEvent)
    + summary_ids_adopted: list[str]           ← new typed field
    ↓
SummaryStore.record_outcomes()                  ← new method (per-summary aggregate)
    → summary_feedback table (counters)
    ↓ (read on /v1/context/pack)
SummaryStore.get_feedback_map()
    ↓
context.pack.build_context_pack(..., feedback)  ← admission demotes/disables
    → low-confidence: omit with reason="summary disabled by feedback"
    → confidence sort: higher-confidence summaries admitted first under budget
```

### Schema change (forward-compatible)

`ContextPackEvalEvent` gains an optional typed `summary_ids_adopted: list[str]`
field. The current Anvil contract already tolerates extra fields (`extra="allow"`)
so older agents that omit the list continue to validate — they simply contribute
no per-summary signal.

### `SummaryStore` extension

Add a `summary_feedback` table keyed by `summary_id`:

| column                   | meaning                                                  |
|--------------------------|----------------------------------------------------------|
| `summary_id`             | PK, foreign-key analog to `action_summaries.summary_id`  |
| `adoption_count`         | quality turns where the summary was actually adopted     |
| `success_count`          | adopted turns that ended in a success outcome            |
| `failure_count`          | adopted turns that ended in a non-success, non-safety    |
| `safety_violation_count` | turns with a safety outcome (regardless of adopted flag) |
| `expand_request_count`   | turns where `evidence_expand_requested=True`             |
| `quality_turns`          | total non-excluded turns where this summary was seen     |
| `updated_at`             | last write timestamp                                     |

`adopted` means the eval record's `adoption_status ∈ {adopted, partial}` AND
`summary_id ∈ summary_ids_adopted`. Excluded statuses (`error`,
`not_available`, `shadow_not_injected`) are skipped entirely.

New `SummaryStore` methods:

- `record_outcomes(summary_ids, *, adoption_status, outcome, evidence_expand_requested)` —
  increments aggregate counters. Idempotency is not required (one row per
  evaluate call is the contract).
- `get_feedback(summary_id) -> SummaryFeedbackRecord | None`
- `get_feedback_map(summary_ids) -> dict[str, SummaryFeedbackRecord]` (batch)

### `eval/summary_feedback.py` (new module)

Provides:

- `SummaryFeedbackRecord` (dataclass): the per-summary aggregate; pure aggregate,
  no raw content.
- `confidence(record) -> float`: Laplace-smoothed `(success_count + 1) / (success_count + failure_count + 2)`. Defaults to 0.5 when no quality turns have been seen.
- `is_disabled(record) -> bool`: True if `safety_violation_count >= 1`
  OR (`adoption_count >= 3` AND `confidence < 0.34`). S2-03 regression pattern.
- `SAFETY_OUTCOMES` set: `{"safety_violation", "unsafe", "harmful"}`.

### Admission integration

`build_context_pack` accepts a new optional `summary_feedback` param — a mapping
`summary_id → SummaryFeedbackRecord`. When present:

1. Disabled summaries are filtered out before admission with
   `omitted.reason = "summary disabled by feedback"`.
2. Remaining summaries are sorted by descending confidence so higher-confidence
   items are admitted first under the token budget. Stable sort: ties preserve
   the retriever's original order.

When `summary_feedback` is empty or missing entries, the admission behaviour is
unchanged (deterministic fallback).

### `/v1/evaluate` and `/v1/context/pack` wiring

- `/v1/evaluate`: if `context_pack_event.summary_ids_adopted` is non-empty AND
  the record is not an excluded status, call
  `summary_store.record_outcomes(...)`. Failures are logged but never raise
  (fail-open).
- `/v1/context/pack`: read `summary_store.get_feedback_map(...)` for the
  resolved candidates and pass it to `build_context_pack`.

## Key invariants

1. Feedback only demotes / filters — it never resurrects a stale or contradicted
   summary (the existing admission rules still run first).
2. A safety_violation, even once, disables the summary.
3. When no feedback rows exist, behaviour matches the pre-#87 baseline.
4. The new table stores only counters — no raw prompts, tool output, or user
   text. Aggregate-safe for future model training feature extraction.
5. `record_outcomes` is fail-open: an error there never breaks `/v1/evaluate`.
