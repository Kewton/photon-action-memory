# Design Note — Issue #70: photon-action-memory Anvil Integration Tests

## Objective
Add photon-side Anvil integration tests covering all acceptance criteria.

## Scope of new test files

| File | Focus |
|---|---|
| `tests/test_anvil_contract.py` | Umbrella contract test: schema, raw log policy, shadow/canary aggregation, evidence expansion safety, full call sequence |
| `tests/test_anvil_context_pack_api.py` | Context pack API with Anvil-specific patterns (raw evidence, upserted summaries) |
| `tests/test_anvil_evaluate.py` | `/v1/evaluate` with Anvil shadow/canary statuses; store + aggregate |
| `tests/test_anvil_evidence_expand.py` | Evidence expansion with `anvil_profile=True` safety profile |
| `tests/test_anvil_feedback_scoring.py` | Summary upsert/retrieval via store; staleness filtering before context pack |

## New fixtures under `tests/fixtures/photon/`

| File | Contents |
|---|---|
| `anvil_raw_tool_log_request.json` | ContextPackRequest from Anvil carrying raw stdout/stderr evidence |
| `anvil_action_summary.json` | ActionSummary Anvil would upsert into the summary store |
| `anvil_shadow_evaluate_log.json` | Shadow/canary evaluate log (3 records: shadow_not_injected, adopted, not_available) |

## Acceptance criteria mapping

1. **`pytest tests/test_anvil_contract.py`** — tests in `test_anvil_contract.py` form the umbrella.
2. **Anvil shared fixtures pass photon schema/API tests** — all new test files load and validate existing `fixtures/v0.2/` fixtures.
3. **unsafe raw log fixture is not prompt-visible** — `test_anvil_contract.py` and `test_anvil_context_pack_api.py` both verify `context_pack.items == []` when raw evidence is present.
4. **shadow/canary evaluate fixtures can be stored and aggregated** — `test_anvil_evaluate.py` posts shadow/canary fixtures to `/v1/evaluate` and verifies SQLite storage; `aggregate_context_pack_eval` is called on the stored records.
5. **evidence expansion safety profile returns no raw output** — `test_anvil_evidence_expand.py` verifies `anvil_profile=True` always denies stdout/stderr.

## Non-goals
- No production code changes — all acceptance criteria are already implemented; only tests are missing.
- Tests intentionally do not duplicate assertions already in existing test files.
