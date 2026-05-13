# Verification — Issue #86

## Focused suites

```
$ python -m pytest tests/test_summary_fidelity.py \
                   tests/test_raw_tool_log_policy.py \
                   tests/test_sidecar_api.py -x
...
============================== 88 passed in 0.42s ==============================
```

All directly-related suites pass, including:

- **`tests/test_summary_fidelity.py`** — 4 new tests:
  - `test_secret_in_fact_text_flags_raw_output_in_field`
  - `test_home_path_in_failed_attempt_outcome_flags_raw_leakage`
  - `test_bearer_token_in_action_command_flags_raw_leakage`
  - `test_clean_fact_does_not_trigger_raw_leakage`
- **`tests/test_raw_tool_log_policy.py`** — 5 new tests for `/v1/summarize`:
  - `test_summarize_facts_must_carry_evidence_ids`
  - `test_summarize_redacts_secrets_in_fact_text`
  - `test_summarize_denies_raw_evidence_and_records_admission`
  - `test_summarize_evidence_ids_referenced_supports_expand_followup`
  - `test_summarize_clean_summary_returns_valid_status`
- **`tests/test_sidecar_api.py`** — retargeted `test_summarize_rejects_invalid_request`
  to reflect the new implementation (empty body → 422 instead of 501).

## Broader regression suite

Shared contracts touched (`schema_v2`, `server`, `SummaryFidelityChecker`),
so the full test suite was run:

```
$ python -m pytest
...
======================== 803 passed, 1 skipped in 2.05s ========================
```

The single skip (`tests/integration/test_mlx_smoke.py`) is the opt-in MLX
smoke test and is unrelated to this change.

## Linting / typing

```
$ python -m ruff check photon_action_memory/ \
        tests/test_summary_fidelity.py tests/test_raw_tool_log_policy.py \
        tests/test_sidecar_api.py
All checks passed!

$ python -m mypy photon_action_memory/api/server.py \
        photon_action_memory/api/schema_v2.py \
        photon_action_memory/eval/summary_fidelity.py
Success: no issues found in 3 source files
```

## Manual contract spot-check

The new `/v1/summarize` behaviour was exercised via the integration tests
above, which directly assert:

1. Facts without `evidence_ids` → `validation_results[*].status == "invalid"`
   with a `missing_evidence_id` issue.
2. `API_KEY=...` embedded in `facts[0].text` → redacted in the returned
   `summary` (`supersecret123456789secret` is not present in the response) and
   reported via `raw_output_in_field`.
3. Two raw `stdout`/`stderr` items in `raw_evidence` → two `deny` entries in
   `admission_decisions` with `policy.raw_evidence_policy == "raw_tool_log_default_deny"`,
   matching `/v1/context/pack`. The raw bodies do not appear anywhere in the
   serialised response.
4. `evidence_ids_referenced` is deduplicated and order-preserving, ready to be
   forwarded to `/v1/evidence/expand`.

## Risk

- Existing `/v1/context/pack` and `/v1/summary/validate` behaviour was not
  altered. The new `raw_output_in_field` issue kind is additive; existing
  callers that inspect `kind` as a string will simply see one more possible
  value (status semantics for callers that branch on `valid|invalid|partial`
  remain correct because the new kind is added to `_BLOCKING_KINDS`).
- `model_extra` is used for `evidence_records` and `raw_evidence` to match the
  surrounding endpoints (`/v1/summary/validate`, `/v1/context/pack`). This
  keeps schema evolution forward-compatible without forcing a v0.3 schema bump.
