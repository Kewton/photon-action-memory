# Anvil PHOTON Integration Notes

This file collects the Anvil-facing notes added by the Anvil integration
issues. It includes both the evidence expansion contract from Issue #66 and
the summary store design note from Issue #68.

## Evidence Expansion Contract

Endpoint: `POST /v1/evidence/expand`

### Anvil-safe usage pattern

```json
{
  "schema_version": "action-memory.v0.2",
  "request_id": "<uuid>",
  "evidence_ids": ["<id1>", "<id2>"],
  "selected_evidence_ids": ["<id1>", "<id2>"],
  "budget": {
    "max_chars_per_evidence": 1200,
    "max_total_chars": 4800
  },
  "policy": {
    "redact_again": true,
    "allow_raw_full_output": false,
    "anvil_profile": true
  }
}
```

### Policy flags

| Flag | Default | Effect |
|---|---|---|
| `anvil_profile` | `false` | When `true`, raw stdout/stderr is always omitted regardless of `allow_raw_full_output`. |
| `selected_evidence_ids` | `null` | When set, only evidence IDs in this list may be expanded; all others are omitted with a stable reason. |
| `redact_again` | `true` | Re-applies the sanitizer before returning the snippet. Keep `true` in Anvil profile. |

### Stable omit reasons

Anvil renderer may rely on these exact strings:

| Reason | When |
|---|---|
| `"evidence_id not found"` | Requested ID has no record in the store. |
| `"evidence_id not in selected_evidence_ids"` | ID is not in the caller-supplied allowlist. |
| `"raw output denied by policy"` | Raw stdout/stderr denied by default policy. |
| `"raw output denied: anvil profile"` | Raw stdout/stderr denied because `anvil_profile=true`. |
| `"no expandable content available"` | Record exists but has no snippet, text, or raw content. |
| `"max_total_chars budget exhausted"` | `max_total_chars` limit reached before this ID was processed. |

### Budget enforcement

- `max_chars_per_evidence` caps each individual snippet.
- `max_total_chars` caps the sum across all expanded items.
- Both limits are applied before sanitizer re-run, so the final snippet may be
  slightly shorter after redaction.

### Evidence not found

A missing `evidence_id` never causes a non-2xx response. It appears in the
`omitted` list with reason `"evidence_id not found"`.

## Summary Store Design Note

### Problem

`/v1/context/pack` previously returned a `summary_store_unavailable` warning
whenever `candidate_summary_ids` were given, because no SQLite summary store
existed. `ActionSummary` objects built from Anvil execution history had nowhere
to persist between sessions.

### Solution

New modules:

| Module | Responsibility |
|---|---|
| `photon_action_memory/memory/summary_store.py` | SQLite CRUD for `ActionSummary`: upsert, get, resolve, search. |
| `photon_action_memory/memory/retrieval.py` | Retrieval with staleness guard pre-filtering. |

New endpoint:

`POST /v1/summary/upsert` stores an `ActionSummary` from Anvil and returns
`{ summary_id, status }`.

Updated endpoint:

`POST /v1/context/pack` resolves `candidate_summary_ids` from the store via
`SummaryRetriever`, then passes the result to `build_context_pack`. Unknown IDs
are skipped.

### Staleness guarantee

`SummaryRetriever._filter_stale` drops summaries whose `validity.status` is
`stale` or `contradicted` before they reach `ContextAdmissionController`, which
provides a second layer of the same check.

When a `StalenessContext` is provided, `StalenessGuard.apply` updates each
summary's validity dynamically so that context-aware signals are honored even
when the stored validity is `valid`.

### SQLite schema

```sql
CREATE TABLE action_summaries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    summary_id      TEXT NOT NULL UNIQUE,
    repo_id         TEXT,
    task_signature  TEXT,
    validity_status TEXT NOT NULL DEFAULT 'valid',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    payload_json    TEXT NOT NULL
);
```

Indexes on `repo_id`, `task_signature`, and `validity_status` support bounded
search by repo and task.

### Default paths

| Variable | Default |
|---|---|
| `PHOTON_ACTION_MEMORY_DB` | `$TMPDIR/photon-action-memory/events.sqlite` |
| `PHOTON_ACTION_MEMORY_SUMMARY_DB` | `$TMPDIR/photon-action-memory/summaries.sqlite` |

## Rollout Policy (Issue #72)

See `workspace/anvil/rollout_policy.md` for the full shadow → canary promotion
checklist and rollback conditions.

### Quick reference

Three gates must all pass before canary injection is enabled:

1. `total_turns >= 10` (configurable `min_turns_for_canary`)
2. `total_raw_tool_tokens_in_prompt == 0` — hard gate, no threshold
3. `fail_open_incident_rate <= 0.05` (configurable `max_fail_open_rate`)

Rollback is triggered immediately if `raw_tool_tokens_in_prompt > 0` or
`fail_open_incident_rate > max_fail_open_rate`.

Key modules:
- `photon_action_memory/context/canary.py` — `CanaryRolloutPolicy`, `is_canary_eligible()`
- `photon_action_memory/eval/metrics.py` — `RolloutMetrics`, `build_rollout_metrics()`
- `tests/fixtures/v0.2/rollout_metrics_fixture.json` — four named gate scenarios
- `tests/test_rollout_policy.py` — 14 tests covering all gates and rollback conditions
