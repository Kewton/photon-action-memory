# Issue #126 — Design

## Goal

v0.4.0 left the PHOTON scorer boundary, v1 checkpoint builder/loader, and the
deterministic fallback in place but disconnected from the live
`/v1/context/pack` ranking path. This Issue closes the loop:

```
/v1/evaluate feedback
  -> feedback snapshot
  -> PHOTON checkpoint candidate
  -> evaluation / promotion
  -> live /v1/context/pack production ranking (shadow / canary / production)
```

without making MLX or a trained checkpoint mandatory for CI and without
letting a learned score override the existing safety / answer-leak / stale
gates.

## Scope decisions

- **Smallest coherent change.** Add the modules required by the acceptance
  criteria and wire them into the existing `/v1/context/pack` path. Do **not**
  do a full slim port of `photon-mlx-develop` — only commit the
  `photon_runtime/UPSTREAM.md` record so future ports have a documented
  contract.
- **No new HTTP endpoint** for export or promotion in this Issue. Feedback
  export and checkpoint registry are exposed as library functions plus a small
  CLI helper that can be driven by a job.
- **Counter-only feedback.** The exporter must not emit raw prompts, raw
  tool stdout/stderr, secrets, or full diffs. It re-uses the
  `summary_feedback` and `context_pack_eval` tables already populated by
  `/v1/evaluate` and the new in-memory `context_pack_ranking_log` table.
- **Fail-open ranking.** Each ranking mode (`deterministic`, `photon_shadow`,
  `photon_canary`, `photon`) must degrade to deterministic ordering when the
  checkpoint is missing, invalid, or MLX is unavailable. The request must
  never fail on a missing checkpoint.
- **Hard gates remain hard.** The PHOTON score is layered on top of the
  admitted-candidate ordering after the answer-leak gate, the staleness /
  contradiction caps, and the safety filter have run. It cannot promote a
  blocked summary back into the pack.

## Plan

### Phase 1 — Feedback export + ranking_log

1. Add `photon_action_memory/eval/ranking_log.py` with
   `ContextPackRankingLogRecord` (PII-safe IDs only) and
   `summary_id_label_for(record, eval_record)` mapping
   `adopted_success / adopted_failure / adopted_safety / ignored / partial /
   not_selected / omitted_by_gate`.
2. Add a `context_pack_ranking_log` SQLite table to `SQLiteEventStore` and a
   `record_ranking_log()` writer. Persist `context_pack_request_id`,
   `summary_id`, `kind`, `position`, `score`, `selected`, `omitted_reason`,
   `outcome_family`, `created_at` — no rendered text or raw content.
3. Add `photon_action_memory/eval/feedback_export.py` with
   `export_action_memory_feedback(...)` producing the
   `action-memory-feedback.v1` JSONL records used by the checkpoint builder
   (one record per `(summary_id, kind)` with weight derived from
   adopted_status × outcome_family and a `feedback_max_updated_at`
   manifest entry).
4. Hook `/v1/context/pack` so each admitted/omitted candidate is appended to
   `context_pack_ranking_log` (kind=`action_summary`, optional second pass for
   raw `omitted_by_gate` items). `/v1/evaluate` writes back the matching
   outcome family.

### Phase 2 — Checkpoint Builder v2

1. Extend `photon_action_memory/models/checkpoint.py` with a
   `CHECKPOINT_FORMAT_V2 = "photon-action-memory.v2"` constant plus an
   `ALLOWED_STATE_KEYS_V2` set adding `summary_weights`,
   `next_action_weights`, `avoid_weights`, and `suppressed_ids`.
2. Make `load_checkpoint_manifest` accept v1 and v2 manifests, returning the
   same `PhotonCheckpoint` shape (v1 keys map to the v2 buckets so callers
   keep working).
3. Extend `checkpoint_builder.write_action_memory_checkpoint` with a
   `format_version="v2"` option, an optional `manifest_source` block
   (`feedback_export_path`, `feedback_max_updated_at`,
   `feedback_record_count`), and an optional `photon_runtime/` subdirectory
   (currently `UPSTREAM.md` only — see Phase 5).
4. Add `build_action_memory_checkpoint_state_v2(records)` that produces the
   richer state from the Phase 1 feedback export. Records with safety outcome
   land in `suppressed_ids` rather than as a positive weight.

### Phase 3 — Registry / promote / rollback

1. Add `photon_action_memory/models/checkpoint_registry.py` with:
   - `CheckpointRegistry(root_dir)` exposing `register_candidate(path)`,
     `promote(candidate_id, *, reason, gate_report)`, `rollback(reason)`,
     `active_path()`, and `previous_path()`.
   - `current` and `previous` pointer files written atomically via
     `os.replace`. A symlink is preferred when supported; otherwise a tiny
     pointer file is used so the registry works on every platform.
   - `promotion_report.json` is appended on each promotion / rollback.
2. Honor `PHOTON_CHECKPOINT_ACTIVE` and `PHOTON_CHECKPOINT_DIR` env vars when
   resolving the active checkpoint path.
3. When `PHOTON_ACTION_MEMORY_CHECKPOINT` is set, the registry returns the
   override path and `auto_promotion_enabled()` returns False. The override
   bypasses the registry entirely so an operator can pin a checkpoint without
   the auto path fighting them.

### Phase 4 — `/v1/context/pack` ranking modes

1. Add `photon_action_memory/ranking/context_ranking.py` defining
   `RankingMode = Literal["deterministic", "photon_shadow", "photon_canary",
   "photon"]` and `resolve_ranking_mode(env)`.
2. `apply_photon_ranking(pack, *, mode, scorer, feedback_snapshot)` runs
   after `build_context_pack` but only re-orders admitted items. It never
   re-admits omitted items.
3. `final_score = clamp(base * (1 - w) + photon_score * w + live_feedback_delta,
   0, 1)`. `live_feedback_delta` only considers feedback updated **after**
   `manifest.source.feedback_max_updated_at` to prevent double counting.
4. Add a `ranking_report` warning to the response that captures the mode and
   `photon_unavailable` reasons in shadow comparisons.

### Phase 5 — `photon_runtime/UPSTREAM.md`

1. Create `photon_action_memory/photon_runtime/__init__.py` and
   `photon_action_memory/photon_runtime/UPSTREAM.md` documenting the upstream
   repo, commit, license, copied files, local changes, and sync policy.
2. Stub-only: do not commit MLX code today; the file becomes the contract for
   the future slim port. The existing scorer continues to import `mlx.core`
   lazily through `PhotonMLXAdapter`.

## Test plan

- `tests/test_summary_feedback.py` — keep existing tests green; add coverage
  for `export_action_memory_feedback` (no raw text, outcome_family carried,
  partial labels split).
- `tests/test_action_memory_checkpoint_builder.py` — extend with v2 builder
  records (`summary_weights`, `suppressed_ids`, manifest source block) and
  v1/v2 round trips.
- `tests/test_action_memory_scorer.py` — add a v2 checkpoint round trip and a
  `photon_runtime/` directory load test.
- `tests/test_photon_adapter.py` — confirm metadata-only v2 and v1
  compatibility on the loader.
- `tests/test_context_pack.py` — add ranking mode tests (deterministic
  default, photon_shadow fail-open with no checkpoint, photon order applied
  when scorer present, hard gates not bypassed, `context_pack_ranking_log`
  table populated, no raw text written).

A new `tests/test_checkpoint_registry.py` covers the registry promote /
rollback atomicity and `PHOTON_ACTION_MEMORY_CHECKPOINT` override path.

## Non-goals

- No actual MLX port of `photon-mlx-develop` files (only the contract file).
- No new external service for canary traffic management beyond the env-var
  ranking mode toggle.
- No online training, no large checkpoint download, no raw-content fields.
