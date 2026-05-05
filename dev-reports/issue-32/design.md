# Issue #32 — Design Note: Action Context Firewall Schema (v0.2)

## Goal

Add v0.2 schema models for the Action Context Firewall milestone (M1).
These schemas are the data contract for the entire v0.2 feature set —
ActionChunk, ActionSummary, EvidenceRef, ContextPack, ContextAdmissionDecision,
SummaryValidationResult — and must be stable before any builder or API work begins.

## Placement

New file: `photon_action_memory/api/schema_v2.py`

Reasons:
- v1 schema stays unchanged; agents on v1 continue to work.
- v0.2 schema version string is `"action-memory.v0.2"`, which is a different Literal type.
- A separate module keeps the diff minimal and reviewable.
- Existing tests in `tests/test_schema.py` are unaffected.

## Schema Version

```
SchemaVersionV2 = Literal["action-memory.v0.2"]
```

All request/response/model objects in v0.2 carry `schema_version: SchemaVersionV2`.

## Forward Compatibility

All models inherit `SidecarModel` (re-used from `schema.py`), which sets
`model_config = ConfigDict(extra="allow")`. This ensures unknown optional fields
do not break validation as the schema evolves.

## Core Models

### ActionChunk
Groups raw EventRecords into a single meaningful action unit (search, edit, test, etc.).
Carries `event_ids`, `outcome`, `risk`, `redaction_status`.

### EvidenceRef
Pointer to a piece of evidence without embedding full content in the prompt.
Key fields: `evidence_id`, `source_event_id`, `source_chunk_id`, `locator` (file/line/command),
`expand_policy` (on_demand_only / always / deny), `staleness`.

### ActionSummary
Core v0.2 schema. Separates:
- `actions_done` — what was executed and its outcome
- `facts` — grounded claims with `evidence_ids` and `confidence`
- `hypotheses` — unconfirmed claims with explicit `status`
- `failed_attempts` — actions that did not succeed with `retry_policy`
- `avoid` — guidance to skip repeated useless actions
- `next_hints` — suggested next actions

### ContextAdmissionDecision
Records whether a memory item was admitted/omitted/expanded/deferred/denied,
along with the `reason` and `policy` that governed the decision.

### ContextPack
The only allowed entry point for memory into an LLM prompt.
Contains `items` (admitted), `omitted`, `warnings`, and `token_budget`.

### SummaryValidationResult
Result of fidelity checks: evidence existence, fact grounding, hypothesis labeling,
staleness, failed-action classification.

## Request/Response Pairs

| API | Request | Response |
|-----|---------|----------|
| POST /v1/context/pack | ContextPackRequest | ContextPackResponse |
| POST /v1/evidence/expand | EvidenceExpandRequest | EvidenceExpandResponse |
| POST /v1/summary/validate | SummaryValidateRequest | SummaryValidateResponse |

## Key Invariants Enforced by Schema

1. `schema_version` is required on all top-level objects.
2. `facts` and `hypotheses` carry `evidence_ids` (list, may be empty for new entries).
3. `failed_attempts` are distinct from `actions_done` — not mixed.
4. `avoid` guidance carries `valid_until` policy string.
5. `EvidenceRef.expand_policy` controls whether detail can be fetched on demand.
6. `StalenessStatus.status` enumerates `valid | stale | partial | contradicted | unknown`.
