# Issue #66 Design — Evidence Expansion Control for Anvil

## Problem

`POST /v1/evidence/expand` was usable by any caller with full flexibility:
- `allow_raw_full_output=True` could expose raw stdout/stderr even for Anvil callers.
- No way to restrict expansion to a caller-owned subset of evidence IDs.
- Omit `reason` strings were unstable (e.g. embedded runtime values), making Anvil renderer brittle.

## Solution

Three targeted additions with no breaking changes:

### 1. `selected_evidence_ids` allowlist on `EvidenceExpandRequest`

Anvil includes only the evidence IDs it collected in the current fixture. Any `evidence_ids` entry that is not in `selected_evidence_ids` is omitted immediately with reason `"evidence_id not in selected_evidence_ids"`. When `selected_evidence_ids` is `null` (the default), all IDs are allowed — backward compatible.

### 2. `anvil_profile: bool = False` on `EvidenceExpandPolicy`

When `True`, raw stdout/stderr (any record whose concise_text is `None` and raw_text is set) is always omitted with reason `"raw output denied: anvil profile"`, regardless of `allow_raw_full_output`. This prevents callers from accidentally opting in to raw output via `allow_raw_full_output=True` in an Anvil context.

### 3. Stable omit reason constants

All six omit reasons are now module-level string constants in `memory/evidence.py` and exported from `__all__`. The values were chosen to remain backward-compatible with existing substring-based tests.

## Files changed

| File | Change |
|------|--------|
| `photon_action_memory/api/schema_v2.py` | Add `anvil_profile` to `EvidenceExpandPolicy`; add `selected_evidence_ids` to `EvidenceExpandRequest` |
| `photon_action_memory/memory/evidence.py` | Add reason constants; implement allowlist filtering and Anvil-profile raw deny in `expand()` |
| `tests/test_evidence_expander.py` | 11 new tests covering all new behaviors |
| `workspace/anvil/summary.md` | Anvil integration contract document |
