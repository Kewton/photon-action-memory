# Anvil ↔ PHOTON Evidence Expansion Contract

## Endpoint

`POST /v1/evidence/expand`

## Anvil-safe usage pattern

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

## Policy flags

| Flag | Default | Effect |
|------|---------|--------|
| `anvil_profile` | `false` | When `true`, raw stdout/stderr is always omitted regardless of `allow_raw_full_output`. |
| `selected_evidence_ids` | `null` | When set, only evidence IDs in this list may be expanded; all others are omitted with a stable reason. |
| `redact_again` | `true` | Re-applies the sanitizer before returning the snippet. Keep `true` in Anvil profile. |

## Stable omit reasons

Anvil renderer may rely on these exact strings:

| Reason | When |
|--------|------|
| `"evidence_id not found"` | Requested ID has no record in the store. |
| `"evidence_id not in selected_evidence_ids"` | ID is not in the caller-supplied allowlist. |
| `"raw output denied by policy"` | Raw stdout/stderr denied by default policy. |
| `"raw output denied: anvil profile"` | Raw stdout/stderr denied because `anvil_profile=true`. |
| `"no expandable content available"` | Record exists but has no snippet, text, or raw content. |
| `"max_total_chars budget exhausted"` | `max_total_chars` limit reached before this ID was processed. |

## Budget enforcement

- `max_chars_per_evidence` caps each individual snippet (default 1200).
- `max_total_chars` caps the sum across all expanded items; remaining IDs are omitted once the budget is exhausted.
- Both limits are applied before sanitizer re-run, so the final snippet may be slightly shorter after redaction.

## Evidence not found → 200 + omitted

A missing `evidence_id` never causes a non-2xx response. It appears in the `omitted` list with reason `"evidence_id not found"`.
