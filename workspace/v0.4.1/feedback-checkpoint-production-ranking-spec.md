# v0.4.1 — Feedback → PHOTON checkpoint → production ranking

This document is the canonical spec for Issue #126. It captures the contract
shipped by the implementation in `photon_action_memory/` and is the file
referenced from the Issue body.

## Pipeline

```
/v1/evaluate feedback
  └─ summary_feedback table          (per-summary aggregates)
  └─ context_pack_ranking_log table  (per-candidate, no raw text)
        │
        ▼
  action-memory-feedback.v1 JSONL export
        │
        ▼
  v2 checkpoint candidate
   ├─ manifest.json     (format=photon-action-memory.v2, source.feedback_max_updated_at)
   ├─ action_memory_state.json   (optional sidecar with the big weight dicts)
   ├─ state.json / weights.npz / integrity.json
   └─ photon_runtime/   (optional — slim port contract per UPSTREAM.md)
        │
        ▼
  CheckpointRegistry
   ├─ candidates/<id>/
   ├─ current   (atomic pointer)
   ├─ previous  (atomic pointer)
   └─ promotion_report.json   (append-only log)
        │
        ▼
  /v1/context/pack ranking mode
   ├─ deterministic   (default, behaves like v0.4.0)
   ├─ photon_shadow   (compute + emit comparison, keep deterministic order)
   ├─ photon_canary   (hash-bucket fraction of requests)
   └─ photon          (full apply, hard gates still in front)
```

## Contracts

### 1. Ranking log (Phase 1)

`photon_action_memory.eval.ranking_log` defines:

- `RankingLogEntry` — write DTO: `(context_pack_request_id, summary_id,
  kind, position, score, selected, omitted_reason)`. **Forbidden** fields:
  rendered text, raw evidence, prompt content.
- `RankingLogOutcome` — written by `/v1/evaluate` to back-fill
  `outcome_family ∈ {success, failure, safety, unknown}` and
  `adoption_status`.
- `classify_label(...)` — Phase 1 labels:
  - `adopted_success` — selected and outcome=success
  - `adopted_failure` — selected and outcome=failure
  - `adopted_safety`  — selected and outcome=safety
  - `partial`         — selected with `adoption_status=partial`
  - `ignored`         — selected but no useful outcome
  - `not_selected`    — admitted to pipeline but lost the budget cut
  - `omitted_by_gate` — denied by quality / safety / stale / contradict /
    answer_leak / disabled / raw_tool_log / premature gate

Storage lives in the SummaryStore SQLite database, table
`context_pack_ranking_log` with a unique `(context_pack_request_id,
summary_id, kind)` constraint so retries are idempotent.

### 2. Feedback export (Phase 1)

`photon_action_memory.eval.feedback_export.export_action_memory_feedback`
joins the ranking log into a `FeedbackExportResult` whose JSONL form is
`action-memory-feedback.v1`. The first line is a manifest header
containing `manifest.source` with:

- `feedback_max_updated_at` — newest `ranking_log.created_at` covered by
  this export. Used by ranking mode `live_feedback_delta` to skip
  already-baked feedback.
- `feedback_record_count`
- `safety_violation_count`
- `label_counts`

Each subsequent line is a `FeedbackExportRecord` with:

- `bucket ∈ {summary_weights, evidence_weights, next_action_weights,
  file_weights, avoid_weights}`
- signed `weight` (partial label is signed by `outcome_family`)
- `safety_violation` boolean — records with True go into `suppressed_ids`
  instead of a numeric bucket.

### 3. Checkpoint v2 (Phase 2)

`photon-action-memory.v2` extends the v1 manifest with:

- `summary_weights`, `next_action_weights`, `avoid_weights` weight buckets.
- `suppressed_ids: list[str]` — hard-banned ids (safety violations).
- Optional `action_memory_state.json` sidecar — merged at load time so the
  manifest stays small. Manifest state wins on collision.
- Optional `photon_runtime/` directory — marker for the slim-port layer.
- `manifest.source` block (carries `feedback_max_updated_at`).

The loader (`load_checkpoint_manifest`) accepts both v1 and v2 manifests
and returns the same `PhotonCheckpoint` DTO (now with `format`, `source`,
and `has_photon_runtime` fields).

The scorer (`PhotonMLXAdapter._score`) returns 0 immediately for any
subject in `suppressed_ids` and otherwise applies v2 buckets per-kind:

- `summary` / `action_summary` → `summary_weights`
- `next_hint` / `next_action`  → `next_action_weights`
- `failed_attempt` / `avoid`   → `avoid_weights`

v1 buckets (`action_weights`, `file_weights`, `evidence_weights`)
continue to work unchanged.

### 4. Registry (Phase 3)

`photon_action_memory.models.checkpoint_registry.CheckpointRegistry` owns:

- `candidates/<id>/` — one directory per candidate.
- `current` — atomic pointer file (single line, candidate id).
- `previous` — atomic pointer file.
- `promotion_report.json` — append-only JSON list of
  `{event, candidate_id, previous_id, reason, created_at, gate_report}`.

Operations:

- `register_candidate(path)` — validates the manifest and returns the id.
- `promote(id, reason, gate_report)` — re-validates manifest + integrity,
  shifts `current` → `previous`, writes the new `current`. Uses
  `os.replace` for atomicity. Safe to retry.
- `rollback(reason, gate_report)` — swaps `current` and `previous`.
- `resolve_active(env)` — resolution order:
  1. `PHOTON_ACTION_MEMORY_CHECKPOINT` (operator override)
  2. `PHOTON_CHECKPOINT_ACTIVE`
  3. local `current` pointer
  4. `PHOTON_CHECKPOINT_DIR/current` pointer
- `auto_promotion_enabled(env)` returns False when the operator override
  is set, so an auto-promote job stops touching `current` while an
  operator is holding the wheel.

### 5. Ranking modes (Phase 4)

`photon_action_memory.ranking.context_ranking.resolve_ranking_mode(env)`
reads `PHOTON_CONTEXT_PACK_RANKING` and returns one of `deterministic |
photon_shadow | photon_canary | photon`.

`apply_ranking_mode(pack, ...)` runs **after** `build_context_pack`. It:

- never re-admits omitted items
- never overrides safety/stale/contradicted/answer-leak/quality gates
  (those have already filtered the input list)
- bails out to deterministic with a `ranking_mode_fallback` warning when
  the scorer is missing, raises, or reports `photon_unavailable`
- in `photon_shadow` keeps the deterministic order and emits a
  `ranking_report` warning containing the per-item base / photon / final
  scores
- in `photon_canary` only re-orders requests whose `request_id` hashes
  into the configured ratio (`PHOTON_CONTEXT_PACK_CANARY_RATIO`)
- combines scores as

  ```
  final = clamp(
      base * (1 - photon_weight)
      + photon_score * photon_weight
      + live_feedback_delta,
      0, 1)
  ```

  with `photon_weight` from `PHOTON_CONTEXT_PACK_PHOTON_WEIGHT` (default
  0.4). `live_feedback_delta` is bounded to ±0.05 and uses the
  manifest's `feedback_max_updated_at` to skip already-baked feedback.

### 6. photon_runtime slim port (Phase 5)

`photon_action_memory/photon_runtime/UPSTREAM.md` is the contract file
covering upstream commit, license, reserved file list, local change
policy, MLX import policy, and sync policy. No upstream files are
copied yet; the directory exists to mark the boundary so future ports do
not silently grow.

## Acceptance test mapping

| Acceptance criterion | Implementation site |
|---|---|
| feedback DB から raw content なしの checkpoint input | `eval/ranking_log.py` (no text columns), `eval/feedback_export.py` (no text fields) |
| `context_pack_ranking_log` 弱い負例 | `classify_label` → `not_selected` |
| `partial` 二極化 | `_signed_weight` in `feedback_export.py` |
| 二層構造 v2 checkpoint | `models/checkpoint_builder.py` `write_action_memory_checkpoint(format_version=v2, use_action_memory_sidecar=True, include_photon_runtime_stub=True)` |
| v1 / metadata-only v2 / runtime v2 load | `load_checkpoint_manifest` accepts both, sidecar merge, `has_photon_runtime` flag |
| atomic promote / rollback | `CheckpointRegistry.promote` / `.rollback` using `os.replace` |
| `PHOTON_ACTION_MEMORY_CHECKPOINT` で auto 無効化 | `resolve_active` + `auto_promotion_enabled` |
| `/v1/context/pack` 4 ranking mode | `ranking/context_ranking.py` |
| PHOTON unavailable で deterministic | `_fallback` returns deterministic pack with `ranking_mode_fallback` warning |
| hard gates 非上書き | `apply_ranking_mode` only re-orders `pack.items` (already gated) |
| 二重加算なし | `live_feedback_delta` keyed off `manifest.source.feedback_max_updated_at` |
| shadow 比較 report | `ranking_report` warning produced in `photon_shadow` |
| canary promotion gate | `photon_canary` only applies when `_canary_includes` true |
| slim port upstream policy | `photon_runtime/UPSTREAM.md` |
| CI が MLX / checkpoint なしで通る | default mode is deterministic, all imports lazy |

## Test surface (Issue #126)

```bash
python -m pytest \
  tests/test_summary_feedback.py \
  tests/test_action_memory_checkpoint_builder.py \
  tests/test_action_memory_scorer.py \
  tests/test_photon_adapter.py \
  tests/test_context_pack.py \
  tests/test_checkpoint_registry.py \
  tests/test_feedback_export.py \
  tests/test_context_ranking.py \
  -q
```

The last three files are added by this Issue.
