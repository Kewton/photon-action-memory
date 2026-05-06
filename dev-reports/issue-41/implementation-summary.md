# Issue #41 - Add Context Pollution Metrics: Implementation Summary

## What Was Built

### `photon_action_memory/eval/pollution.py` (new)

Implements four public symbols exported via `__all__`:

**`POLLUTION_REPORT_SCHEMA`** - Schema version string `"pollution-metrics.v1"`.

**`PollutionRecord`** - Dataclass representing per-turn pollution measurements.

Fields:

| Field | Type | Description |
|---|---|---|
| `context_pack_tokens` | int | Estimated tokens in admitted ContextPack items |
| `summary_tokens_in_prompt` | int | Tokens from admitted action_summary items |
| `raw_tool_tokens_in_prompt` | int | Tokens from raw tool items in admitted list (always 0 with deny policy) |
| `tokens_saved_vs_raw` | int | From `token_budget.tokens_saved_vs_raw` |
| `tokens_saved_vs_full_transcript` | int or None | `full_transcript_tokens - context_pack_tokens` when provided |
| `stale_summary_incidents` | int | Omitted summaries with stale/contradicted reason |
| `duplicate_context_incidents` | int | Omitted summaries with duplicate reason |
| `ungrounded_fact_incidents` | int | Issues with kind `ungrounded_fact` from validation results |
| `hypothesis_as_fact_incidents` | int | Issues with kind `hypothesis_as_fact` from validation results |
| `total_summaries_evaluated` | int | Admitted + omitted action_summary items |
| `total_facts_evaluated` | int | Sum of `len(s.facts)` across input summaries |

**`PollutionReport`** - Pydantic model for the aggregate report. Aggregate-only: no raw logs, prompts, or tool outputs.

Fields: `schema_version`, `total_records`, `total_context_pack_tokens`, `total_summary_tokens_in_prompt`, `total_raw_tool_tokens_in_prompt`, `total_tokens_saved_vs_raw`, `tokens_saved_vs_full_transcript`, `stale_summary_incidents`, `duplicate_context_incidents`, `ungrounded_fact_incidents`, `hypothesis_as_fact_incidents`, `duplicate_context_rate`, `ungrounded_fact_rate`, `hypothesis_as_fact_rate`.

Rates computed as `incidents / total_evaluated`; return `0.0` when denominator is zero.

**`measure_context_pack(pack, *, summaries, validation_results, full_transcript_tokens)`** - Computes one `PollutionRecord` from a `ContextPack`.

- Token measurements come from `pack.items` using `estimate_tokens` from `context.render`.
- Stale/duplicate incidents come from `pack.omitted[*].reason` substring matching.
- Fidelity incidents come from `SummaryValidationResult.issues[*].kind`.
- `total_facts_evaluated` requires the original `summaries` list to be passed.

**`build_pollution_report(records)`** - Aggregates a `Sequence[PollutionRecord]` into a `PollutionReport`.

### `photon_action_memory/eval/__init__.py` (modified)

Added imports and `__all__` entries for:
- `PollutionRecord`
- `PollutionReport`
- `build_pollution_report`
- `measure_context_pack`

### `tests/test_context_pollution.py` (new)

33 focused tests covering:

- Empty pack yields all-zero record.
- `raw_tool_tokens_in_prompt == 0` with only raw items (fixture proving default deny policy).
- `raw_tool_tokens_in_prompt == 0` with mixed summaries and raw items.
- Admitted summary tokens counted correctly.
- `tokens_saved_vs_raw` comes from `token_budget`.
- `tokens_saved_vs_full_transcript` computed and non-negative.
- `tokens_saved_vs_full_transcript` is None when not provided.
- Stale and contradicted summaries counted as incidents.
- Duplicate omissions counted as duplicate_context_incidents.
- Ungrounded fact incidents from validation results.
- Hypothesis-as-fact incidents from validation results.
- Total facts and summaries evaluated correctly.
- Aggregate report tokens summed.
- Stale incidents summed across records.
- Rates computed correctly (duplicate, ungrounded, hypothesis-as-fact).
- Rates are 0.0 when denominator is zero.
- `tokens_saved_vs_full_transcript` aggregated, None when all None, partial aggregation.
- Report shape: required fields present, raw content fields absent.
- Schema version correct.
- Total records matches input length.
- End-to-end: raw deny keeps aggregate `total_raw_tool_tokens_in_prompt == 0`.
- End-to-end: full pipeline produces a valid report with expected values.

## Design Decisions

**Dataclass for PollutionRecord, Pydantic for PollutionReport.** Follows local style: `raw_policy.py` uses dataclasses for intermediate data; `metrics.py` uses Pydantic for aggregate report output.

**Incident detection via reason substring matching.** Stale/duplicate incidents are detected by substring in `OmittedItem.reason`. This is deterministic and requires no additional context, since the admission controller writes these reasons explicitly.

**`total_facts_evaluated` requires caller to pass summaries.** The ContextPack does not retain the original fact count. Callers pass the same `summaries` list used to build the pack.

**`raw_tool_tokens_in_prompt` is structurally zero.** The deny policy in `build_context_pack` ensures raw items never reach `pack.items`. The measurement still checks `item.kind` against `_RAW_ITEM_KINDS` to guard against future policy changes.

**Rates return 0.0 on zero denominator.** Consistent with the `_rate` helper in `metrics.py`.
