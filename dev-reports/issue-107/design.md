# Issue #107 Design

## Goal

When the quality gate detects `premature_termination_risk`, preserve useful
summary facts instead of dropping the whole seed. The risky part is the
overlapping `next_hints`, so the prompt renderer should support suppressing
only those hints while leaving `FACT`, `HYPOTHESIS`, `FAILED`, and `AVOID`
content available to Anvil.

## Approach

- Keep the existing `summary_quality_gate` warning kind and warning message
  unchanged for Anvil compatibility.
- Extend `SummaryQualityGateResult` with
  `suppressed_next_hint_indices`, an internal tuple of prompt-render hint
  indices selected by the existing premature-risk detector.
- Extend `render_summary()` with `exclude_next_hint_indices` so callers can
  render a summary without selected hint rows.
- In `build_context_pack()`, render a suppressed version when the quality gate
  reports risky hints. A quality-gate `reject` caused by those hints is treated
  as a soft block: the summary can still pass normal admission using the
  hint-suppressed text.
- Keep hard rejection behavior for low-value overlap when there are no specific
  risky hint indices to suppress.

## Compatibility

The API-visible warning shape remains:

```text
kind=summary_quality_gate
message="<summary_id>: premature_termination_risk: direct next_hint overlaps current task"
```

No new ContextPack schema field is required. The only API-visible behavior
change is that affected summaries now appear in `items` with prompt text that
omits the risky `HINT:` rows, and their `admission_reason` notes the
suppression.

## Out of Scope

- Detector threshold changes.
- Multilingual tokenization changes.
- Anvil-side warning filtering.
