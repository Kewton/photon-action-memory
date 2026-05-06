# Issue #38 - EvidenceExpander Implementation Summary

## What was added

### `photon_action_memory/memory/evidence.py` (new)
Core implementation of the `EvidenceExpander` class.

**Internal model: `_Candidate`**
Each candidate record is normalised into a structured view:
- `evidence_id` - resolved from `evidence_id` field, falling back to `event_id`
- `kind` - event kind string
- `summary` - brief description
- `concise_text` - selected concise content (`snippet`, plus `text`/`content` for non-raw kinds)
- `raw_text` - raw full output (`stdout` / `stderr` / `text` / `content` for raw kinds)
- `locator` - `Locator` assembled from flat fields or a nested `locator` dict

**Snippet selection priority**
1. `snippet` field - always preferred as selected concise content
2. `text` field - selected concise content only when `kind` is not in `RAW_DENIED_KINDS`
3. `content` field - concise only when `kind` is not in `RAW_DENIED_KINDS`
4. `stdout` / `stderr` / `text` / `content` for raw kinds - raw full output, denied by default

**Default-deny for raw full output**
When `policy.allow_raw_full_output=False` (the default) and only raw output is available, the evidence is omitted with a descriptive reason. This mirrors the `raw_tool_log_default_deny` policy already applied in `build_context_pack`.

**Budget enforcement**
- `max_chars_per_evidence` (default 1200): snippet is truncated and `truncated=True` is set.
- `max_total_chars` (optional): once the running total reaches the cap, remaining evidence IDs are omitted with reason `"max_total_chars budget exhausted"`.

**Sanitizer re-run**
When `policy.redact_again=True` (default), `sanitize_text_with_report` is called on the final snippet before it is placed in `ExpandedEvidence`. `redaction_status` is set to `"redacted"` or `"clean"` accordingly.

### `photon_action_memory/api/server.py` (updated)
Added `POST /v1/evidence/expand` route:
- Fetches all store events via `event_store.list_events()` and adds their payloads to the record pool.
- Merges any `evidence_records` list from `request.model_extra` (extra Pydantic fields).
- Builds an `EvidenceExpander` and calls `expand()`.
- Fails open: any exception returns a valid `EvidenceExpandResponse` with all requested IDs in `omitted` with the error message.

### `tests/test_evidence_expander.py` (new)
38 focused deterministic tests covering all acceptance criteria.
