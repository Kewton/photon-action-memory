# Implementation Summary — Issue #86

## What changed

### `/v1/summarize` is now a firewall endpoint (was M2 stub returning 501)

`POST /v1/summarize` accepts an agent-built **draft `ActionSummary`** plus optional
`raw_evidence` and `evidence_records` (passed through pydantic `model_extra`),
applies the Action Context Firewall, and returns a sanitized summary together
with validation signals.

Response shape (`SummarizeResponse`):

- `summary`: the draft with secrets / home paths / token-like strings redacted
  in every prompt-visible string field
  (`facts/hypotheses/failed_attempts/avoid/actions_done/next_hints/validity.reason`)
- `validation_results`: one `SummaryValidationResult` (grounding + leakage
  signals), with `raw_output_in_field` added for redacted fields so callers can
  see *what* was scrubbed
- `admission_decisions`: deny entries for every `raw_evidence` item
  (same `raw_tool_log_default_deny` policy used by `/v1/context/pack`)
- `omitted`: corresponding `OmittedItem` entries
- `evidence_ids_referenced`: deduplicated, order-preserving union of every
  evidence_id referenced by the firewalled summary — feeds directly into
  `/v1/evidence/expand` for redacted snippets on demand

The handler is fail-open: on internal exception it returns the original draft
with a single `summarize_error` issue rather than a 500.

### `SummaryFidelityChecker` gained `raw_output_in_field` detection

The checker now also scans every prompt-visible string field on an
`ActionSummary` using `photon_action_memory.context.raw_policy.has_sensitive_content`
and emits a blocking `raw_output_in_field` issue when secret patterns / bearer
tokens / `sk-`/`ghp_`-style tokens / `/home|/Users|/root` paths are detected.
This means `/v1/summary/validate` also surfaces leakage, not just the new
`/v1/summarize` route.

`raw_output_in_field` is added to `_BLOCKING_KINDS`, so status flips to
`invalid` when leakage is found.

### Schema additions (`photon_action_memory/api/schema_v2.py`)

- `SummarizeRequest`: `schema_version`, `request_id`, `draft_summary`
  (`evidence_records` and `raw_evidence` come in via `model_extra`, consistent
  with `/v1/context/pack` and `/v1/summary/validate`)
- `SummarizeResponse`: documented above
- Both are added to `__all__`

## Files touched

- `photon_action_memory/api/schema_v2.py` — `SummarizeRequest` / `SummarizeResponse`
- `photon_action_memory/api/server.py` — implements `/v1/summarize`, plus
  module-level helpers `_summarize_with_firewall`,
  `_coerce_summarize_raw_items`, `_deny_summarize_raw_evidence`,
  `_apply_summary_firewall`, `_collect_summary_evidence_ids`
- `photon_action_memory/eval/summary_fidelity.py` — `_check_raw_leakage` and
  blocking-kind expansion
- `tests/test_sidecar_api.py` — `/v1/summarize` is no longer a 501 stub; the
  empty-body case now exercises the request schema (422)
- `tests/test_summary_fidelity.py` — 4 new tests for the
  `raw_output_in_field` checker rule
- `tests/test_raw_tool_log_policy.py` — 5 new integration tests covering the
  `/v1/summarize` evidence-grounding + raw-firewall contract

## How acceptance criteria are satisfied

| AC | Where verified |
|----|---------------|
| `/v1/summarize` 生成 summary の prompt-visible fact は evidence_ids を持つ | `test_summarize_facts_must_carry_evidence_ids` (returns `missing_evidence_id`, status `invalid`) |
| raw stdout/stderr/secret は `ContextPack.items[].text` に入らない | `test_summarize_redacts_secrets_in_fact_text` (secret is scrubbed from `facts[0].text`) + `test_summarize_denies_raw_evidence_and_records_admission` (raw items never appear in serialised `summary`) + existing `/v1/context/pack` raw policy untouched |
| `validation_results` で grounding / raw leakage の状態を確認できる | All `/v1/summarize` integration tests + new `_check_raw_leakage` unit tests in `tests/test_summary_fidelity.py` |
| `/v1/evidence/expand` と連携し、必要時だけ redacted snippet を返せる | `test_summarize_evidence_ids_referenced_supports_expand_followup` — caller takes `evidence_ids_referenced` and forwards it to existing `/v1/evidence/expand` (whose `policy.redact_again` + `policy.allow_raw_full_output=false` defaults already enforce redaction) |

## Design choices

- **Reuse, don't duplicate.** `has_sensitive_content` and `evaluate_raw_item`
  already implement the raw firewall for `/v1/context/pack`. The new endpoint
  delegates to them so the policy stays single-sourced.
- **Redact + flag, not just flag.** The returned summary is redacted in place
  so callers can safely persist or forward it. The matching
  `raw_output_in_field` issue is appended to `validation_results` so callers
  can decide whether to keep the redacted summary or reject it.
- **No schema breakage.** Existing `/v1/summary/validate` consumers see
  `raw_output_in_field` as a new (additive) issue kind — `SummaryValidationIssue.kind`
  was already `str`. `ContextAdmissionDecision.item_kind` was already
  defined as `Literal[...] | str`, so emitting `raw_tool_log` continues to be
  valid.
- **Stub test was kept, retargeted.** `test_summarize_is_m2_stub` is replaced
  by `test_summarize_rejects_invalid_request` so we still cover the route at
  a basic-handshake level.
