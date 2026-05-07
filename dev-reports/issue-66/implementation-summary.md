# Issue #66 Implementation Summary

## Changes

### `photon_action_memory/api/schema_v2.py`
- `EvidenceExpandPolicy`: added `anvil_profile: bool = False`
- `EvidenceExpandRequest`: added `selected_evidence_ids: list[str] | None = None`

### `photon_action_memory/memory/evidence.py`
- Added six stable reason constants: `REASON_NOT_FOUND`, `REASON_NOT_IN_SELECTION`, `REASON_RAW_OUTPUT_DENIED`, `REASON_RAW_OUTPUT_DENIED_ANVIL`, `REASON_NO_CONTENT`, `REASON_BUDGET_EXHAUSTED`
- `EvidenceExpander.expand()`:
  1. Builds a `frozenset` from `selected_evidence_ids` if provided; IDs not in the set → omit with `REASON_NOT_IN_SELECTION`
  2. When `policy.anvil_profile` is True and raw_text would be used → omit with `REASON_RAW_OUTPUT_DENIED_ANVIL` (ignores `allow_raw_full_output`)
  3. All omit paths now use the stable constants instead of inline strings

### `tests/test_evidence_expander.py`
- 11 new tests: selected-ID allowlist (4), Anvil-profile raw deny (3), stable reason API round-trips (4)
- Imported `REASON_NOT_IN_SELECTION` and `REASON_RAW_OUTPUT_DENIED_ANVIL` for exact-match assertions

### `workspace/anvil/summary.md`
- New: documents the Anvil-safe request pattern, policy flags, and stable reason strings

## Acceptance criteria status

| Criterion | Status |
|-----------|--------|
| Anvil fixture の selected evidence id だけ展開できる | `selected_evidence_ids` allowlist |
| raw stdout/stderr は anvil profile では omitted | `anvil_profile=True` hard-denies raw output |
| `max_chars_per_evidence` と `max_total_chars` が守られる | Pre-existing, unchanged |
| sanitizer が再適用される | Pre-existing, unchanged |
| evidence not found は 200 + omitted | Pre-existing, unchanged |
| Anvil renderer が扱いやすい stable reason を返す | Module-level reason constants |
