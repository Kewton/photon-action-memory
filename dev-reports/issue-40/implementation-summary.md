# Issue #40 - StalenessGuard: Implementation Summary

## What Was Built

### `photon_action_memory/memory/staleness.py` (new)

Implements three public classes exported via `__all__`:

**`FileFingerprinter`** - Static helper for computing stable content fingerprints.
- `fingerprint_content(content)` -> 16-hex-char SHA-256 prefix for full file content.
- `fingerprint_line_range(content, start, end)` -> fingerprint for a 1-indexed inclusive line range.
- `line_range_key(path, start, end)` -> canonical `"path:start:end"` dict key.

**`StalenessContext`** - Dataclass representing the current execution context passed to the guard.
- `current_commit`, `current_branch`, `current_task_signature` - present repo/task state.
- `current_file_fingerprints: dict[str, str] | None` - `None` = not tracking (check skipped); `{}` = tracking but nothing found.
- `current_line_fingerprints: dict[str, str] | None` - same semantics.
- `refuted_claims: list[str]` - fact/hypothesis texts contradicted by later evidence.

**`StalenessCheckResult`** - Dataclass returned by the guard.
- `status: StalenessStatusKind | str` - one of `valid`, `stale`, `partial`, `contradicted`, `unknown`.
- `reason: str | None` - prompt-safe human-readable reason (no raw file contents, truncated commit hashes).

**`StalenessGuard`** - Main evaluation class.

`check(summary, context, *, summary_branch, summary_file_fingerprints, summary_line_fingerprints) -> StalenessCheckResult`

Staleness triggers (evaluated in priority order):

| Priority | Trigger | Status |
|---|---|---|
| 1 | Refuted claim matches a fact or hypothesis | `contradicted` |
| 2 | Commit hash changed | `stale` |
| 3 | Branch changed | `stale` |
| 4 | Task signature changed | `stale` |
| 5 | File fingerprint changed | `stale` |
| 6 | Expected file missing from current fingerprints | `unknown` |
| 7 | Line-range fingerprint changed | `partial` |
| 8 | Expected line range missing from current | `unknown` |
| - | No triggers fired | `valid` |

`apply(summary, context, ...) -> ActionSummary`

Calls `check()` and returns a new `ActionSummary` (original is never mutated) with `validity.status` and `validity.reason` set to the guard result.

### `photon_action_memory/context/admission.py` (modified)

Updated `ContextAdmissionController.evaluate()` to include `validity.reason` in the omit reason when a summary is stale or contradicted:

```python
# Before:
return "omit", f"summary is {summary.validity.status}"

# After:
base_reason = f"summary is {summary.validity.status}"
if summary.validity.reason:
    return "omit", f"{base_reason}: {summary.validity.reason}"
return "omit", base_reason
```

This propagates the guard's detailed reason (e.g., `"commit changed (abc12345->xyz99999)"`) into `ContextAdmissionDecision.reason` and `OmittedItem.reason`.

### `tests/test_staleness.py` (new)

47 focused tests covering:

- `FileFingerprinter` determinism, hex format, and line-range key format.
- Per-trigger staleness: commit, branch, task signature, file fingerprint, line range, missing reference, contradiction.
- Edge cases: skipping checks when context fields are `None` (fail-open behavior).
- `apply()` correctness and non-mutation of originals.
- End-to-end integration: guard -> apply -> build_context_pack omits stale summaries.
- Reason propagation: `validity.reason` appears in `OmittedItem.reason` and `ContextAdmissionDecision.reason`.
- Prompt-safety: no raw file content in reasons; full 40-char commit hashes are truncated to 8 chars.

## Design Decisions

**Fail-open for untracked state.** If the caller does not provide `current_file_fingerprints` (leaves it as `None`), the file fingerprint check is skipped entirely. An empty dict `{}` explicitly means "we checked but found nothing." This prevents false positives when fingerprinting is not set up.

**Priority ordering prevents status demotion.** Contradiction is checked first so that a summary contradicted by newer evidence is never merely marked `stale`.

**Line-range changes yield `partial`, not `stale`.** A changed line range suggests part of the summary may still be valid. The caller can decide whether to include `partial` summaries; the admission controller admits them by default (only `stale` and `contradicted` are omitted).

**`unknown` passes admission.** A summary where the reference cannot be found is marked `unknown`, not `stale`. The admission controller only omits `stale` and `contradicted`, so unknown summaries are admitted (fail-open).

**Reasons are prompt-safe by construction.** File paths appear verbatim (truncated at 80 chars). Commit hashes are truncated to 8 chars. No file contents or event payloads ever appear in reasons.
