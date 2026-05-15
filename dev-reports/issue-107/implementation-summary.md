# Issue #107 Implementation Summary

## Changes

- Added selective hint suppression to `render_summary()` via
  `exclude_next_hint_indices`.
- Added internal `suppressed_next_hint_indices` to quality-gate results.
- Updated context-pack assembly so `premature_termination_risk` no longer
  forces whole-seed omission when specific risky hints can be suppressed.
- Preserved the existing `summary_quality_gate` warning kind and message.
- Updated admission token accounting and duplicate tracking to use the actual
  rendered text after hint suppression.

## Behavior

For an S2-style seed whose facts are useful but whose `next_hints` overlap the
current task:

- Before: the entire summary could be omitted by the quality gate.
- After: facts remain in the ContextPack; overlapping `HINT:` rows are omitted.

Verification-only hints remain allowed when they are not mixed with a risky
direct-edit hint. When a direct-edit hint and a verification hint coexist, only
the direct-edit hint is flagged for suppression.
