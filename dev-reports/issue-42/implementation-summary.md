# Issue #42 - Update Eval Runner for Context Firewall Comparisons: Implementation Summary

## What Was Built

### `photon_action_memory/eval/comparison.py` (new)

Implements comparison-specific APIs exported via `__all__`:

**`COMPARISON_REPORT_SCHEMA`** - Schema version string `"comparison-metrics.v1"`.

**`EVAL_CONDITIONS`** - Frozenset of the six named conditions:
`no_memory`, `full_transcript`, `static_summary_memory`, `retrieval_memory`,
`photon_summary_only`, `photon_summary_evidence`.

**`ComparisonRecord`** - Pydantic model for one normalized comparison turn record.

Fields:

| Field | Type | Description |
|---|---|---|
| `condition` | str | Named eval condition; defaults to `no_memory` |
| `outcome` | str or None | Turn outcome for task_success_rate computation |
| `repeated_exploration_occurred` | bool | True when the agent re-explored already-visited paths |
| `failed_action_retry` | bool | True when the agent retried a previously failed action |
| `duplicate_context_incidents` | int | Per-turn duplicate context count from pollution.py |
| `ungrounded_fact_incidents` | int | Per-turn ungrounded fact count from pollution.py |
| `hypothesis_as_fact_incidents` | int | Per-turn hypothesis-as-fact count from pollution.py |
| `total_summaries_evaluated` | int | Per-turn summary evaluation count |
| `total_facts_evaluated` | int | Per-turn fact evaluation count |

Extra fields are silently ignored (`extra="ignore"`) so raw prompt/log/tool-output
fields in fixture JSON are never stored or reported.

**`ConditionSummary`** - Aggregate metrics for one named condition.

Fields: `condition`, `total_records`, `task_success_rate`,
`repeated_exploration_rate`, `failed_action_retry_rate`,
`duplicate_context_rate`, `ungrounded_fact_rate`, `hypothesis_as_fact_rate`.

**`ComparisonReport`** - Aggregate-only report across all conditions.

Fields: `schema_version`, `total_records`, `conditions` (sorted alphabetically).

**`build_comparison_report(records)`** - Aggregates a `Sequence[RawComparisonRecord]`
into a `ComparisonReport`.  Records are grouped by `condition`; each group produces
one `ConditionSummary`.  Rates return `0.0` on zero denominator.

Success outcomes: `"accepted"`, `"success"`, `"completed"`.

### `photon_action_memory/eval/runner.py` (modified)

Three new functions added alongside the existing runner, preserving all existing behavior:

**`run_comparison(records, *, output_path)`** - Runs comparison eval over
condition-labeled records and optionally writes aggregate JSON.

**`run_comparison_fixture(fixture_path, *, output_path)`** - Loads a JSON fixture
(list or `{records: [...]}` object) via the existing `load_fixture` and runs
comparison eval.

**`write_comparison_report(report, output_path)`** - Writes the aggregate
`ComparisonReport` as JSON; creates parent directories automatically.

### `photon_action_memory/eval/__init__.py` (modified)

Added imports and `__all__` entries for:
- `COMPARISON_REPORT_SCHEMA`
- `EVAL_CONDITIONS`
- `ComparisonRecord`
- `ComparisonReport`
- `ConditionSummary`
- `build_comparison_report`
- `run_comparison`
- `run_comparison_fixture`
- `write_comparison_report`

### `tests/test_eval_runner_comparison.py` (new)

33 focused tests covering:

- `EVAL_CONDITIONS` contains all six named conditions.
- Empty input produces zero report.
- `task_success_rate` for `accepted`, `success`, `completed`, and non-success outcomes.
- `repeated_exploration_rate` computed correctly.
- `failed_action_retry_rate` computed correctly.
- Pollution rates (`duplicate_context_rate`, `ungrounded_fact_rate`,
  `hypothesis_as_fact_rate`) computed per condition from incident fields.
- Zero-denominator rates return `0.0`.
- Multiple conditions grouped and sorted alphabetically.
- All six named conditions can appear in one report.
- Dict (fixture-style) records parsed correctly; unknown fields ignored.
- Report dump contains no raw log, prompt, tool_output, or per-record fields.
- `schema_version` is `"comparison-metrics.v1"`.
- `run_comparison` returns a `ComparisonReport`.
- `run_comparison` writes aggregate-only JSON; no raw fields in output file.
- `run_comparison` with no `output_path` does not write any file.
- `run_comparison_fixture` loads JSON list fixture.
- `run_comparison_fixture` loads `{records: [...]}` fixture.
- `run_comparison_fixture` writes output when path provided.
- `ComparisonRecord` defaults are safe.
- Negative incident counts are rejected by Pydantic validation.

## Design Decisions

**New module `comparison.py` rather than extending `metrics.py`.** The comparison
semantics (condition grouping, retry tracking, pollution integration) are orthogonal
to shadow-mode next-action hit evaluation.  A separate module keeps both surfaces
focused and independently testable.

**Pollution metrics integrated via per-record incident counts, not by importing
`PollutionRecord`.** The `ComparisonRecord` carries the five pollution count fields
that `PollutionRecord` exposes.  Callers measure one `PollutionRecord` per turn and
copy the relevant fields into `ComparisonRecord`.  This avoids duplicating
`pollution.py` logic while still surfacing pollution rates per condition.

**`extra="ignore"` on `ComparisonRecord`.** Consistent with `ShadowEvalRecord` and
`EvalModel`.  Raw log, prompt, and tool-output fields in fixture JSON are silently
dropped so they never reach the aggregate report.

**`RawComparisonRecord = ComparisonRecord | Mapping[str, Any]`.** Mirrors the
`RawRecord` alias in `metrics.py`, allowing `run_comparison` to accept both typed
objects and raw dict records from `load_fixture`.

**Conditions sorted alphabetically in output.** Deterministic ordering makes diffs
stable across fixture changes.

**Success outcomes: `accepted`, `success`, `completed`.** Derived from the outcome
vocabulary used in existing fixtures and `MetricsReport.outcome_counts`.
