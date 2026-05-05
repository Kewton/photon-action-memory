# 03. Schema and API

## 1. Existing APIs from v0.1.0

v0.2.0 でも以下は維持する。

```
GET  /health
POST /v1/events
POST /v1/suggest
POST /v1/summarize
POST /v1/evaluate
```

v0.2.0 では以下を追加する。

```
POST /v1/context/pack
POST /v1/evidence/expand
POST /v1/summary/validate
```

## 2. Schema Version

v0.2.0 の schema version は次とする。

```
action-memory.v0.2
```

すべての request / response は `schema_version` を持つ。

## 3. ActionChunk

ActionChunk は、複数の EventRecord を意味のある action 単位にまとめたもの。

```json
{
  "schema_version": "action-memory.v0.2",
  "chunk_id": "chunk_017",
  "session_id": "sess_001",
  "turn_id": "turn_006",
  "repo_id": "repo_001",
  "commit": "abc123",
  "kind": "repo_search|file_inspection|failure_reproduction|edit_attempt|test_verification|answer_prep|other",
  "event_ids": ["evt_041", "evt_042", "evt_043"],
  "started_at": "2026-04-30T10:00:00Z",
  "ended_at": "2026-04-30T10:02:00Z",
  "summary": "Searched SessionStore and found primary implementation in src/session/store.rs.",
  "outcome": "useful|failed|partial|irrelevant|unknown",
  "risk": "low|medium|high",
  "redaction_status": "sanitized"
}
```

## 4. EvidenceRef

EvidenceRef は、prompt に全文を入れずに参照可能にする evidence pointer である。

```json
{
  "schema_version": "action-memory.v0.2",
  "evidence_id": "evt_052",
  "source_event_id": "evt_052",
  "source_chunk_id": "chunk_018",
  "kind": "tool_result|file_read|test_output|build_output|diff|case|summary",
  "summary": "cargo test session_persistence failed with serialization mismatch.",
  "locator": {
    "file": "tests/session_persistence.rs",
    "line_start": 42,
    "line_end": 57,
    "command": "cargo test session_persistence"
  },
  "redaction_status": "sanitized",
  "expand_policy": "on_demand_only",
  "max_expand_chars": 1200,
  "staleness": {
    "status": "valid",
    "reason": null
  }
}
```

## 5. ActionSummary

ActionSummary は v0.2.0 の中核 schema である。

```json
{
  "schema_version": "action-memory.v0.2",
  "summary_id": "sum_001",
  "session_id": "sess_001",
  "repo_id": "repo_001",
  "commit": "abc123",
  "task_signature": "fix-session-persistence-test",
  "summary_level": "turn|chunk|session|case",
  "source_chunk_ids": ["chunk_017", "chunk_018"],
  "actions_done": [
    {
      "kind": "search",
      "target": "SessionStore",
      "outcome": "primary implementation found",
      "status": "useful",
      "evidence_ids": ["evt_041"]
    },
    {
      "kind": "test",
      "command": "cargo test session_persistence",
      "outcome": "failed with serialization mismatch",
      "status": "unresolved",
      "evidence_ids": ["evt_052"]
    }
  ],
  "facts": [
    {
      "text": "SessionStore implementation is in src/session/store.rs.",
      "evidence_ids": ["evt_041"],
      "confidence": 0.95
    }
  ],
  "hypotheses": [
    {
      "text": "The failure may be related to the serde path.",
      "evidence_ids": ["evt_052"],
      "confidence": 0.62,
      "status": "open"
    }
  ],
  "failed_attempts": [
    {
      "action": "rerun cargo test session_persistence without code changes",
      "outcome": "same failure",
      "evidence_ids": ["evt_052"],
      "retry_policy": "avoid_until_files_changed"
    }
  ],
  "avoid": [
    {
      "action": "repo-wide grep for SessionStore",
      "reason": "already performed successfully",
      "valid_until": "files_changed",
      "evidence_ids": ["evt_041"]
    }
  ],
  "next_hints": [
    {
      "kind": "read",
      "target": "src/session/store.rs",
      "reason": "primary implementation file",
      "confidence": 0.78
    },
    {
      "kind": "inspect",
      "target": "tests/session_persistence.rs",
      "reason": "failing test location",
      "confidence": 0.74
    }
  ],
  "token_cost": {
    "estimated_summary_tokens": 240,
    "estimated_raw_tokens": 5200,
    "tokens_saved_vs_raw": 4960
  },
  "validity": {
    "status": "valid|stale|partial|contradicted",
    "reason": null
  }
}
```

## 6. ContextAdmissionDecision

ContextAdmissionDecision は、ある memory item を prompt に入れるかどうかの判断を表す。

```json
{
  "schema_version": "action-memory.v0.2",
  "decision_id": "adm_001",
  "item_id": "sum_001",
  "item_kind": "action_summary|evidence_ref|warning|raw_event",
  "decision": "admit|omit|expand|defer|deny",
  "reason": "useful_recent_task_state",
  "risk": "low|medium|high",
  "estimated_tokens": 180,
  "policy": {
    "raw_evidence_policy": "deny_by_default",
    "detail_level": "summary_only"
  }
}
```

## 7. ContextPack

ContextPack は、agent prompt に入れてよい memory の唯一の入口である。

```json
{
  "schema_version": "action-memory.v0.2",
  "request_id": "turn_123",
  "session_id": "sess_001",
  "repo_id": "repo_001",
  "mode": "summary_only|summary_plus_evidence|none",
  "items": [
    {
      "kind": "action_summary",
      "id": "sum_001",
      "text": "Searched SessionStore; primary implementation found in src/session/store.rs. cargo test session_persistence failed with serialization mismatch.",
      "evidence_ids": ["evt_041", "evt_052"],
      "admission_reason": "useful_recent_task_state"
    },
    {
      "kind": "avoid",
      "id": "avoid_001",
      "text": "Do not rerun repo-wide grep for SessionStore unless files changed.",
      "evidence_ids": ["evt_041"],
      "admission_reason": "repeat_exploration_guard"
    },
    {
      "kind": "hypothesis",
      "id": "hyp_001",
      "text": "The serde path may be related, but this is not confirmed.",
      "evidence_ids": ["evt_052"],
      "admission_reason": "open_hypothesis"
    }
  ],
  "omitted": [
    {
      "kind": "raw_tool_output",
      "id": "evt_052_raw",
      "reason": "raw output exceeds budget; summary is sufficient"
    }
  ],
  "warnings": [
    {
      "kind": "stale_risk|missing_evidence|repeat_failure|drift",
      "message": "One previous test command failed and should not be repeated without code changes."
    }
  ],
  "token_budget": {
    "max_tokens": 800,
    "estimated_tokens": 260,
    "tokens_saved_vs_raw": 5200
  }
}
```

## 8. POST /v1/context/pack

### Request

```json
{
  "schema_version": "action-memory.v0.2",
  "request_id": "turn_123",
  "agent": {
    "name": "anvil",
    "version": "0.2.x"
  },
  "repo": {
    "root": "/path/to/repo",
    "name": "Anvil",
    "branch": "feature/example",
    "commit": "abc123"
  },
  "task": {
    "user_request": "Fix failing session persistence test.",
    "mode": "plan|act|answer",
    "summary": "Fix failing session persistence test."
  },
  "working_memory": {
    "active_task": "Fix failing session persistence test.",
    "constraints": [],
    "touched_files": [],
    "unresolved_errors": [],
    "active_precautions": []
  },
  "recent_event_ids": ["evt_041", "evt_052"],
  "candidate_summary_ids": ["sum_001"],
  "budget": {
    "max_memory_tokens": 800,
    "max_evidence_chars": 1200,
    "raw_evidence_policy": "deny_by_default",
    "detail_level": "summary_only"
  }
}
```

### Response

```json
{
  "schema_version": "action-memory.v0.2",
  "request_id": "turn_123",
  "model_version": "photon-action-memory-v0.2.0",
  "sidecar_status": "ok",
  "context_pack": {
    "schema_version": "action-memory.v0.2",
    "request_id": "turn_123",
    "session_id": "sess_001",
    "repo_id": "repo_001",
    "mode": "summary_only",
    "items": [],
    "omitted": [],
    "warnings": [],
    "token_budget": {
      "max_tokens": 800,
      "estimated_tokens": 0,
      "tokens_saved_vs_raw": 0
    }
  },
  "admission_decisions": []
}
```

## 9. POST /v1/evidence/expand

### Request

```json
{
  "schema_version": "action-memory.v0.2",
  "request_id": "expand_001",
  "evidence_ids": ["evt_052"],
  "reason": "Need exact failure message before deciding next test.",
  "budget": {
    "max_chars_per_evidence": 1200,
    "max_total_chars": 2000
  },
  "policy": {
    "redact_again": true,
    "allow_raw_full_output": false,
    "allow_selected_snippet": true
  }
}
```

### Response

```json
{
  "schema_version": "action-memory.v0.2",
  "request_id": "expand_001",
  "expanded": [
    {
      "evidence_id": "evt_052",
      "kind": "test_output",
      "summary": "cargo test session_persistence failed with serialization mismatch.",
      "snippet": "selected sanitized stderr snippet here",
      "locator": {
        "command": "cargo test session_persistence",
        "file": "tests/session_persistence.rs",
        "line_start": 42,
        "line_end": 57
      },
      "redaction_status": "sanitized",
      "truncated": true
    }
  ],
  "omitted": [
    {
      "evidence_id": "evt_052_raw",
      "reason": "full raw output denied by policy"
    }
  ]
}
```

## 10. POST /v1/summary/validate

### Request

```json
{
  "schema_version": "action-memory.v0.2",
  "request_id": "validate_001",
  "summary_ids": ["sum_001"],
  "checks": [
    "evidence_exists",
    "fact_grounding",
    "hypothesis_labeling",
    "staleness",
    "failed_action_classification",
    "redaction_status"
  ]
}
```

### Response

```json
{
  "schema_version": "action-memory.v0.2",
  "request_id": "validate_001",
  "results": [
    {
      "summary_id": "sum_001",
      "status": "valid",
      "score": 0.94,
      "issues": [],
      "checked_at": "2026-04-30T10:05:00Z"
    }
  ]
}
```

## 11. POST /v1/summarize update

v0.2.0 では `/v1/summarize` は ActionSummary を返す。

### Request

```json
{
  "schema_version": "action-memory.v0.2",
  "request_id": "summarize_001",
  "session_id": "sess_001",
  "chunk_ids": ["chunk_017", "chunk_018"],
  "summary_level": "chunk|turn|session",
  "policy": {
    "require_evidence_ids": true,
    "separate_fact_and_hypothesis": true,
    "include_failed_attempts": true,
    "include_avoid_guidance": true
  }
}
```

### Response

```json
{
  "schema_version": "action-memory.v0.2",
  "request_id": "summarize_001",
  "summary": {
    "summary_id": "sum_001"
  },
  "validation": {
    "status": "valid",
    "score": 0.94
  }
}
```
