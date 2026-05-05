# Issue #32 — Implementation Summary

## What was implemented

New file: `photon_action_memory/api/schema_v2.py`

All v0.2 schema models for the Action Context Firewall milestone (M1), following
the patterns established in `photon_action_memory/api/schema.py` (v1).

### Models added

| Model | Purpose |
|-------|---------|
| `ActionChunk` | Groups raw EventRecords into a meaningful action unit |
| `EvidenceRef` | Evidence pointer with locator, expand_policy, staleness |
| `ActionSummary` | Core schema: separates facts / hypotheses / failed_attempts / avoid |
| `ContextAdmissionDecision` | Records admit/omit/expand/defer/deny decisions |
| `ContextPack` | Sole entry point for memory into an LLM prompt |
| `SummaryValidationResult` | Result of fidelity/grounding checks |

### Supporting sub-models

`StalenessStatus`, `Locator`, `AdmissionPolicy`, `TokenBudget`, `ActionDone`,
`Fact`, `Hypothesis`, `FailedAttempt`, `AvoidGuidance`, `NextHint`, `TokenCost`,
`Validity`, `ContextPackItem`, `OmittedItem`, `ContextPackWarning`,
`SummaryValidationIssue`

### Request/Response pairs added

| API endpoint | Request | Response |
|-------------|---------|----------|
| POST /v1/context/pack | `ContextPackRequest` | `ContextPackResponse` |
| POST /v1/evidence/expand | `EvidenceExpandRequest` | `EvidenceExpandResponse` |
| POST /v1/summary/validate | `SummaryValidateRequest` | `SummaryValidateResponse` |

### Supporting models for requests

`ContextPackBudget`, `EvidenceExpandBudget`, `EvidenceExpandPolicy`,
`ExpandedEvidence`, `OmittedEvidence`

## Design decisions

**Separate file, not appended to schema.py.**
`schema_v2.py` keeps the v1 contract untouched and the diff reviewable.
v1 agents continue to work without any change.

**Re-use `SidecarModel` from v1.**
The `extra="allow"` base config is shared, ensuring forward compatibility
across all v0.2 models without repeating the config.

**Re-use `AgentInfo`, `RepoInfo`, `TaskState`, `WorkingMemory` from v1.**
These types are schema-version-agnostic carriers; re-importing avoids duplication
and keeps request payloads consistent with v1 conventions.

**`SchemaVersionV2 = Literal["action-memory.v0.2"]`** is a distinct type from
`SchemaVersion = Literal["action-memory.v1"]`, so wrong-version payloads fail
with `ValidationError` at the Pydantic literal check.

**`StalenessStatus` defaults to `status="unknown"`** so a freshly-created
EvidenceRef is not assumed valid without an explicit check.

**`Validity` defaults to `status="valid"`** matching the plan's intent that a
newly-created ActionSummary starts as valid until a staleness guard invalidates it.

## Files changed

- `photon_action_memory/api/schema_v2.py` — new file, 340 lines
- `tests/test_schema_v2.py` — new file, 50 tests
- `dev-reports/issue-32/design.md` — new file
- `dev-reports/issue-32/implementation-summary.md` — this file
- `dev-reports/issue-32/verification.md` — see verification

## Files NOT changed

- `photon_action_memory/api/schema.py` — v1 schema unchanged
- `photon_action_memory/__init__.py` — `SCHEMA_VERSION` remains `"action-memory.v1"`
- All existing tests — unchanged, all still pass
