# Implementation Summary: Issue #35

## Files added / modified

| File | Change |
|------|--------|
| `photon_action_memory/memory/summaries.py` | New: ActionSummaryBuilder, SummaryCanonicalizer, SummaryStateUpdater |
| `tests/test_summaries.py` | New: 59 tests covering all three classes |
| `dev-reports/issue-35/design.md` | New: design rationale |
| `dev-reports/issue-35/implementation-summary.md` | This file |
| `dev-reports/issue-35/verification.md` | Verification results |

## Public API

### `ActionSummaryBuilder`

```python
builder = ActionSummaryBuilder()
summary: ActionSummary = builder.build(chunk, summary_id=None)
```

Converts one `ActionChunk` into an `ActionSummary` using deterministic heuristics.
All claims are grounded in `chunk.event_ids`.

### `SummaryCanonicalizer`

```python
canonicalizer = SummaryCanonicalizer()
result: CanonicalizeResult = canonicalizer.canonicalize(summary)
# result.summary - cleaned ActionSummary
# result.removed_ungrounded_facts - int
# result.warnings - list[str]
```

Removes `Fact` objects that have no `evidence_ids` and updates `validity` accordingly.

### `SummaryStateUpdater`

```python
updater = SummaryStateUpdater()
s_t: ActionSummary = updater.update(s_prev, chunk, summary_id=None)
```

Incremental state update: `S_t = update(S_{t-1}, ActionChunk_t)`.

## Acceptance criteria mapping

| Criterion | Implementation |
|-----------|---------------|
| ActionSummary from ActionChunk | `ActionSummaryBuilder.build()` |
| Facts require evidence_ids | Builder skips facts when `event_ids=[]`; Canonicalizer strips any that slip through |
| Hypotheses separated, with status/confidence | `outcome="partial"` -> `Hypothesis(status="open", confidence=0.5)` |
| Failed actions not in facts | `outcome="failed"` -> `FailedAttempt` only |
| Avoid/next_hints representable | `outcome="irrelevant"` -> `AvoidGuidance`; chunk-kind heuristics -> `NextHint` |
| Incremental update | `SummaryStateUpdater.update(prev, chunk)` |
