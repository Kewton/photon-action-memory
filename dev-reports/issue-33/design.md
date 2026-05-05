# Issue 33 Design: JSON Fixtures for v0.2 Schemas

## Context

Issue #33 is Milestone 1 of the v0.2.0 plan: add JSON fixtures and validation tests
for the five new v0.2 schema models introduced in `workspace/v0.2.0/03_schema_and_api.md`.

The v0.1 schema (`schema.py`, `SCHEMA_VERSION = "action-memory.v1"`) is untouched.

## Schema Models to Add

New file: `photon_action_memory/api/schema_v2.py`

| Model | Key purpose |
|---|---|
| `ActionChunk` | Groups multiple events into an action unit |
| `EvidenceRef` | Pointer to evidence expandable on demand |
| `ActionSummary` | Structured summary with facts/hypotheses/failed_attempts/avoid |
| `ContextAdmissionDecision` | Per-item admit/omit decision |
| `ContextPack` | Only prompt-visible memory packet |

All models inherit `V2Model(BaseModel, extra="allow")` for forward-compatible unknown fields.
`schema_version` is a required `Literal["action-memory.v0.2"]` field on top-level models.

## Fixtures to Add

Directory: `tests/fixtures/v0.2/`

| File | Covers |
|---|---|
| `action_chunk_valid.json` | ActionChunk round-trip |
| `evidence_ref_valid.json` | EvidenceRef round-trip |
| `action_summary_valid.json` | Full ActionSummary with facts, hypotheses, failed_attempts, avoid |
| `context_pack_omits_raw.json` | ContextPack with raw tool output in `omitted`, not in `items` |

## Tests to Add

File: `tests/test_schema_v2.py`

- Round-trip validation for each fixture file
- Missing required field → `ValidationError` (parametrized)
- Unknown optional fields preserved (extra="allow")
- `facts` / `hypotheses` / `failed_attempts` / `avoid` separation asserted
- `context_pack_omits_raw` fixture: `items` has no raw tool output; `omitted` records it

## Dependency on Issue #32

Issue #32 covers the full implementation of v0.2 schema models and API endpoints.
This issue (33) adds only the Pydantic DTO layer and fixture tests needed to validate
the M1 acceptance criteria. No server-side routes are added here.
