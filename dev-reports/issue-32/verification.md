# Issue #32 — Verification

## Test results

```
pytest tests/test_schema_v2.py -v
50 passed in 0.07s
```

```
pytest tests/test_schema.py tests/test_import.py -v
14 passed in 0.14s
```

## Acceptance criteria check

| Criterion | Status |
|-----------|--------|
| All request/response/model objects include `schema_version` | PASS — enforced as required Literal field on all top-level models |
| Unknown optional fields do not break validation | PASS — `extra="allow"` via `SidecarModel`; verified by 5 parametrized tests |
| Missing required fields produce validation errors | PASS — verified for `summary`, `summary_id`, `chunk_id`, `decision`, `token_budget`, `evidence_ids` |
| `facts` / `hypotheses` / `failed_attempts` / `avoid` represented separately | PASS — four distinct list fields on `ActionSummary`; tested with values in all four simultaneously |
| `EvidenceRef` represents source event/chunk/locator/expand policy | PASS — `source_event_id`, `source_chunk_id`, `locator: Locator`, `expand_policy`, `staleness` all present |

## Tests covering each criterion

### schema_version required
- `TestActionChunk::test_schema_version_required`
- `TestEvidenceRef::test_schema_version_required`
- `TestActionSummary::test_schema_version_required`
- `TestContextAdmissionDecision::test_schema_version_required`
- `TestContextPack::test_schema_version_required`
- `TestContextPackRequest::test_schema_version_required`
- `TestEvidenceExpand::test_schema_version_required_on_request`
- `TestSummaryValidate::test_schema_version_required_on_request`
- `test_wrong_schema_version_fails[*]` — 4 parametrized cases

### Unknown optional fields allowed
- `TestActionChunk::test_unknown_fields_preserved`
- `TestEvidenceRef::test_unknown_fields_preserved`
- `TestActionSummary::test_unknown_fields_preserved`
- `TestContextPack::test_unknown_fields_preserved`
- `TestSummaryValidationResult::test_unknown_fields_preserved`
- `test_unknown_optional_fields_do_not_break_validation[*]` — 5 parametrized cases

### Required fields cause validation errors
- `TestActionChunk::test_missing_required_summary_fails`
- `TestActionSummary::test_missing_summary_id_fails`
- `TestContextAdmissionDecision::test_missing_decision_fails`
- `TestContextPack::test_token_budget_required`
- `TestEvidenceExpand::test_missing_evidence_ids_fails`

### facts/hypotheses/failed_attempts/avoid separate
- `TestActionSummary::test_facts_hypotheses_failed_attempts_avoid_are_separate`
- `TestActionSummary::test_full_round_trip`

### EvidenceRef fields
- `TestEvidenceRef::test_full_payload_with_locator`
- `TestEvidenceRef::test_minimal_round_trip` (expand_policy, staleness defaults)
- `TestEvidenceRef::test_locator_is_optional`

## Regression check

All 14 pre-existing tests in `test_schema.py` and `test_import.py` pass without modification.
