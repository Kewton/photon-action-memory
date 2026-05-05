# Issue #37 Implementation Summary

## [P0][v0.2][M3] Enforce raw tool log default deny policy

### Problem

Raw tool output (stdout, stderr, grep output, build logs, full file content) could
potentially reach the prompt-visible `ContextPack.items[*].text` through extra fields
on `ContextPackRequest` or direct calls to `build_context_pack`.  Secret-like strings,
absolute home paths, and token-like values must never be emitted in prompt-visible context.

---

### Changes

#### New file: `photon_action_memory/context/raw_policy.py`

Core default-deny policy module.

- `RAW_DENIED_KINDS` - frozenset of kinds unconditionally denied:
  `stdout`, `stderr`, `grep_output`, `build_log`, `file_content`, `raw_output`,
  `tool_output`, `raw_tool_log`, `shell_output`, `command_output`
- `RawEvidenceItem` - dataclass for candidate raw items (`item_id`, `kind`, `content`, `source`)
- `has_sensitive_content(text)` - detects secret KV pairs, Bearer tokens, prefixed
  API-key tokens (`sk-`, `ghp_`, `ghs_`, `xox*`), and absolute home paths
  (`/home/`, `/Users/`, `/root/`)
- `evaluate_raw_item(item)` - always returns `("deny", reason)`; reason encodes whether
  denial is kind-based, sensitive-content-based, or default-policy-based

#### Updated: `photon_action_memory/context/pack.py`

- Added optional `raw_items: list[RawEvidenceItem] | None` parameter to `build_context_pack()`
- Each raw item is evaluated via `evaluate_raw_item()` and:
  - Added to `pack.omitted` with the deny reason
  - Produces a `ContextAdmissionDecision(decision="deny", item_kind="raw_tool_log", policy=AdmissionPolicy(raw_evidence_policy="raw_tool_log_default_deny"))`
- Raw items are **never** added to `pack.items`

#### Updated: `photon_action_memory/api/server.py`

- Added `_extract_raw_items(request)` helper that reads `request.model_extra["raw_evidence"]`
  (a list of dicts) and converts to `RawEvidenceItem` instances
- Passes extracted raw items to `build_context_pack()`
- Since `SidecarModel` uses `extra="allow"`, agents can attach `raw_evidence` as an extra
  field on the standard `ContextPackRequest` without breaking schema validation

#### New test file: `tests/test_raw_tool_log_policy.py`

28 tests covering all acceptance criteria:

| Category | Tests |
|---|---|
| Kind-based denial (stdout, stderr, grep, build_log, file_content, all kinds) | 7 |
| Sensitive content detection (secrets, bearer, tokens, home paths, safe content) | 6 |
| Sensitive content -> deny in evaluate_raw_item | 2 |
| build_context_pack - raw items stay out of items | 6 |
| raw_tool_tokens_in_prompt is approximately 0 | 2 |
| API integration (extras denied, policy in decisions, no-extras, secret denied) | 4 |
| Unknown kind -> default deny | 1 |

---

### Policy Design

The policy is unconditional default-deny: there is no code path through which a
`RawEvidenceItem` can be admitted.  `evaluate_raw_item` always returns `"deny"`.

The denial reason is specific enough to diagnose the cause:
- `"raw tool log default deny policy: kind 'stdout' is always denied"` - kind match
- `"raw tool log default deny policy: sensitive content detected"` - pattern match
- `"raw tool log default deny policy: raw evidence denied by default"` - catch-all

The `ContextAdmissionDecision.policy.raw_evidence_policy` field is set to
`"raw_tool_log_default_deny"` for all denied raw items, enabling downstream tooling
to filter decisions by policy type.
