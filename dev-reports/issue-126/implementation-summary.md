# Issue #126 — Implementation Summary

## What landed

Five new modules + five wired-up files implement the v0.4.1 feedback →
PHOTON checkpoint → production ranking pipeline. The change is the
smallest coherent set that closes the acceptance criteria; the actual
slim port of `photon-mlx-develop` is deliberately deferred to a future
issue and only the upstream contract is shipped.

### New modules

- `photon_action_memory/eval/ranking_log.py`
  - `RankingLogEntry` / `RankingLogOutcome` DTOs (no raw text fields).
  - `RankingLogStore` — SQLite-backed table `context_pack_ranking_log`
    with a unique `(context_pack_request_id, summary_id, kind)`
    constraint and indexes on request_id / summary_id.
  - `classify_label(...)` — Phase 1 label classifier returning one of
    `adopted_success / adopted_failure / adopted_safety / partial /
    ignored / not_selected / omitted_by_gate`.
  - `outcome_family_from_record(...)` — maps `(adoption_status, outcome)`
    into `success / failure / safety / unknown`.

- `photon_action_memory/eval/feedback_export.py`
  - `FeedbackExportRecord` + `FeedbackExportResult` (manifest header
    carries `feedback_max_updated_at`, `label_counts`, etc.).
  - `export_action_memory_feedback(store, …)` reads ranking-log rows and
    emits one signed-weight record per row.
  - `write_export_jsonl` / `iter_export_jsonl` for sidecar / streaming
    callers.
  - Partial labels are signed by outcome_family; safety records carry
    `safety_violation=True` so the v2 builder routes them to
    `suppressed_ids`.

- `photon_action_memory/models/checkpoint_registry.py`
  - `CheckpointRegistry` owning `candidates/<id>/`, atomic `current` /
    `previous` pointer files (`os.replace`), and an append-only
    `promotion_report.json`.
  - `register_candidate / promote / rollback / resolve_active /
    auto_promotion_enabled`.
  - `PHOTON_ACTION_MEMORY_CHECKPOINT` operator override bypasses the
    registry pointers and disables auto promotion.

- `photon_action_memory/ranking/context_ranking.py`
  - `resolve_ranking_mode(env)` (`deterministic / photon_shadow /
    photon_canary / photon`).
  - `apply_ranking_mode(pack, mode, scorer, …)` — fail-open re-ordering
    that never re-admits omitted items and never overrides hard gates.
  - Canary bucket is request-id hashed so it is stable per request.
  - `live_feedback_delta` is bounded to ±0.05 and skipped when the
    manifest has no `feedback_max_updated_at` so we never double count.

- `photon_action_memory/photon_runtime/__init__.py` +
  `photon_action_memory/photon_runtime/UPSTREAM.md`
  - Slim-port contract: upstream repo, commit
    (`3426681b3e89e897bcbae70995bbfc18a29da82c`), license (MIT),
    reserved file list, local-change policy, MLX import policy, sync
    policy. **No upstream files are copied yet**, intentionally.

### Modified modules

- `photon_action_memory/models/checkpoint.py`
  - Adds `CHECKPOINT_FORMAT_V2`, `ALLOWED_STATE_KEYS_V2`,
    `ACTION_MEMORY_STATE_FILENAME`, `PROMOTION_REPORT_FILENAME`,
    `PHOTON_RUNTIME_DIRNAME`.
  - `PhotonCheckpoint` now carries `format`, `source`,
    `has_photon_runtime`.
  - `load_checkpoint_manifest` accepts v1 and v2 manifests, merges the
    optional `action_memory_state.json` sidecar, and detects the
    `photon_runtime/` directory.

- `photon_action_memory/models/checkpoint_builder.py`
  - `write_action_memory_checkpoint(..., format_version, source,
    use_action_memory_sidecar, include_photon_runtime_stub)`.
  - `build_action_memory_checkpoint_state_v2(records)` aggregates
    `action-memory-feedback.v1` records into the v2 buckets plus
    `suppressed_ids`.
  - `_clean_runtime_state` is now format-aware.

- `photon_action_memory/models/photon_adapter.py`
  - `_score` returns 0.0 for any subject in `suppressed_ids` (v2 only).
  - Reads the v2 buckets per-kind (`summary` →
    `summary_weights`, `next_hint/next_action` →
    `next_action_weights`, `failed_attempt/avoid` → `avoid_weights`).

- `photon_action_memory/memory/summary_store.py`
  - Owns a `RankingLogStore` keyed off the same SQLite connection.

- `photon_action_memory/api/server.py`
  - `/v1/context/pack` writes ranking-log rows derived from the
    admission decisions.
  - `/v1/context/pack` invokes `apply_ranking_mode(...)` when the env
    selects a non-deterministic mode. The scorer is built via
    `make_action_memory_scorer()`, which already fails open.
  - `/v1/evaluate` back-fills `outcome_family` / `adoption_status` on
    the matching ranking-log rows.

### New tests

- `tests/test_checkpoint_registry.py` — promote / rollback / atomic
  pointers / operator override / external-path rejection.
- `tests/test_feedback_export.py` — outcome-family carry-through,
  signed partial labels, safety routing, manifest source header, JSONL
  round trip, raw-text absence guard.
- `tests/test_context_ranking.py` — mode resolver, weight / canary
  clamps, scorer-missing fallback, `photon_unavailable` fallback, photon
  reorder, shadow report, canary in/out, omitted-items not re-admitted,
  empty pack short circuit.

### Extended tests

- `tests/test_summary_feedback.py` — `/v1/context/pack` writes
  ranking-log rows without rendered text, `/v1/evaluate` back-fills the
  outcome family, label resolves to `adopted_success`.
- `tests/test_action_memory_checkpoint_builder.py` — v2 builder
  buckets, full v2 round trip with sidecar + `photon_runtime/`,
  metadata-only v2 round trip.
- `tests/test_photon_adapter.py` — v2 manifest acceptance with
  `source` block, `suppressed_ids` returns score 0.0.

### Documentation

- `workspace/v0.4.1/feedback-checkpoint-production-ranking-spec.md` —
  canonical Issue #126 spec (referenced from the Issue body).
- `workspace/v0.4.1/README.md` — v0.4.1 release notes.
- `dev-reports/issue-126/{design,implementation-summary,verification}.md`.

## Decisions worth remembering

- The ranking log lives in `SummaryStore`'s SQLite database so a single
  `/v1/evaluate` write touches both the per-summary aggregates and the
  per-candidate log atomically.
- The label `omitted_by_gate` is detected purely from the
  `omitted_reason` string returned by the admission controller — no
  separate gate enum is introduced, keeping the change minimal.
- PHOTON scoring runs **after** admission. By only re-ordering
  `pack.items`, the implementation guarantees that the answer-leak /
  safety / staleness / contradiction gates are never bypassed.
- The slim port is **not** performed — only the contract is shipped.
  Doing the port in the same Issue would have added thousands of lines
  of upstream code with no test coverage on this side. The contract
  defines the rules so a follow-up port can be reviewed against them.
- The shadow report is emitted as a `ContextPackWarning` of kind
  `ranking_report` because the existing response schema already
  forwards warnings to operators; no new response field is needed.
