# Issue 33 Implementation Summary

## What Was Added

### `photon_action_memory/api/schema_v2.py` (new)

Five top-level Pydantic models for `schema_version: "action-memory.v0.2"`:

| Model | Description |
|---|---|
| `ActionChunk` | Groups EventRecords into a named action unit with outcome/risk |
| `EvidenceRef` | Pointer to on-demand expandable evidence |
| `ActionSummary` | Structured summary with facts / hypotheses / failed_attempts / avoid / next_hints |
| `ContextAdmissionDecision` | Per-item admit/omit decision with policy |
| `ContextPack` | Sole prompt-visible memory packet; raw output kept in `omitted` |

Supporting inner models: `EvidenceStaleness`, `EvidenceLocator`, `ActionEntry`,
`FactEntry`, `HypothesisEntry`, `FailedAttemptEntry`, `AvoidEntry`, `NextHintEntry`,
`TokenCost`, `SummaryValidity`, `AdmissionPolicy`, `ContextPackItem`, `OmittedItem`,
`ContextPackWarning`, `TokenBudget`.

All models inherit `V2Model(BaseModel, extra="allow")` for forward-compatible unknown fields.

### `tests/fixtures/v0.2/` (new directory, 4 files)

| File | Schema | Purpose |
|---|---|---|
| `action_chunk_valid.json` | ActionChunk | repo_search chunk, outcome=useful |
| `evidence_ref_valid.json` | EvidenceRef | test_output ref with locator, on_demand_only |
| `action_summary_valid.json` | ActionSummary | Full summary covering all four categories |
| `context_pack_omits_raw.json` | ContextPack | summary_only mode; raw_tool_output in omitted |

### `tests/test_schema_v2.py` (new, 18 tests)

- Round-trip fixture validation for all four fixtures
- `fact / hypothesis / failed_attempt / avoid` separation asserted
- `context_pack` confirms raw tool output appears only in `omitted`
- `schema_version` required (parametrized across all 5 top-level models)
- Missing required field → `ValidationError` (parametrized)
- Unknown optional fields preserved via `extra="allow"`

## Key Design Decisions

- `TokenCost` and `TokenBudget` integer counters default to `0` so they work as
  `default_factory` targets without requiring callers to specify token budgets
  upfront. The spec examples always provide explicit values; 0 is a safe sentinel.
- `ContextAdmissionDecision.estimated_tokens` remains required (no default) because
  an admission decision without a token estimate is not meaningful.
- The v1 schema (`schema.py`) is untouched; v0.2 lives entirely in `schema_v2.py`.

## Dependency Note

Schema models and fixtures are self-contained. Issue #32 (full v0.2 API endpoints)
can import from `schema_v2` without modification.
