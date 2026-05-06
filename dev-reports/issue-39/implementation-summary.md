# Issue #39 - SummaryValidation and Fidelity Checks Implementation Summary

## What was added

### `photon_action_memory/eval/summary_fidelity.py` (new)

Core implementation of the `SummaryFidelityChecker` class.

**Module-level constants**

- `_UNCERTAINTY_KEYWORDS` - tuple of words that indicate hypothesis-level uncertainty
  (`appears`, `could`, `likely`, `maybe`, `might`, `perhaps`, `possibly`, `presumably`,
  `seems`, `suspect`, `unclear`, `uncertain`, `probably`)
- `_UNCERTAINTY_PATTERN` - pre-compiled `re.Pattern` with word-boundary anchors matching
  those keywords case-insensitively; word boundaries prevent false matches inside longer words
- `_FAILURE_OUTCOMES` - frozenset of outcome/status strings treated as failure indicators
  (`failed`, `failure`, `error`, `fail`)
- `_BLOCKING_KINDS` - frozenset of issue `kind` values that cause `"invalid"` status
  (`missing_evidence_id`, `ungrounded_fact`, `failed_action_misclassified`)

**`SummaryFidelityChecker`**

Constructor accepts an optional `records` list (evidence dicts). Evidence IDs are extracted
from `evidence_id` or `event_id` fields and stored in an internal set for O(1) grounding
lookups. Without records, only structural checks run.

`check(summary) -> SummaryValidationResult` - runs all checks, computes score and status:

- **`_check_facts`** - for each `Fact`:
  - `missing_evidence_id` (blocking): `evidence_ids` list is empty
  - `ungrounded_fact` (blocking): `evidence_ids` present but none found in evidence records
    (only when records were provided); message contains only the missing IDs (up to 3) and a count
  - `hypothesis_as_fact` (non-blocking): fact text matches `_UNCERTAINTY_PATTERN`; message
    names the matched word - no evidence content is embedded
- **`_check_actions_done`** - for each `ActionDone`:
  - If outcome/status indicates failure and the command/target is not found in any
    `failed_attempts.action` -> `failed_action_misclassified` (blocking)
  - If outcome/status indicates success and the command/target matches a `failed_attempts.action`
    -> `failed_action_misclassified` (blocking): contradiction between actions_done and
    failed_attempts for the same action

`_compute_score` - deduction formula, clamped to `[0.0, 1.0]`, rounded to 4 decimal places:
```
n_total = max(1, len(facts) + len(failed_attempts) + len(actions_done))
deduction = min(1.0, (n_blocking + n_non_blocking * 0.5) / n_total)
score = max(0.0, 1.0 - deduction)
```

`_compute_status`:
- `"valid"` - no issues
- `"invalid"` - at least one issue with `kind` in `_BLOCKING_KINDS`
- `"partial"` - issues present, none blocking

`check_all(summaries) -> list[SummaryValidationResult]` - delegates to `check()` per summary.

**Prompt-safety guarantee**: issue `message` fields contain only evidence IDs (up to 3 at a time),
counts, field indices, and the matched uncertainty keyword. Raw evidence content, secrets, or
full evidence bodies are never embedded.

### `photon_action_memory/eval/__init__.py` (updated)

Added `SummaryFidelityChecker` import and `__all__` export.

### `photon_action_memory/api/server.py` (updated)

Added `POST /v1/summary/validate` route inside `create_app()`:

- Imports `ActionSummary`, `SummaryValidateRequest`, `SummaryValidateResponse` from `schema_v2`.
- Imports `SummaryFidelityChecker` from `eval.summary_fidelity`.
- Reads `summaries` extra field (list of `ActionSummary` dicts) from `request.model_extra`.
  Malformed items are skipped with a warning log - they do not abort the request.
- Reads `evidence_records` extra field (list of dicts) and merges with store-backed event
  payloads to form the record pool passed to the checker.
- Calls `checker.check_all(summaries)` and returns a `SummaryValidateResponse`.
- **Fail-open**: any unhandled exception is logged at WARNING level; the response is returned
  with an empty `results` list - no HTTP 5xx is raised.

### `tests/test_summary_fidelity.py` (new)

45 focused deterministic tests covering all acceptance criteria.
