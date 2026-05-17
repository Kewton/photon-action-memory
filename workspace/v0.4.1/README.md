# PHOTON Action Memory v0.4.1 Notes

v0.4.1 closes the loop between `/v1/evaluate` feedback and the live
`/v1/context/pack` ranking path that was opened in v0.4.0. The new pieces
keep the operator opt-in defaults from v0.4.0: nothing changes for a
deployment that does not set `PHOTON_CONTEXT_PACK_RANKING` or a checkpoint
override.

## Current Defaults

| Area | Default |
|---|---|
| Context pack ranking | `deterministic` (PHOTON ranking is opt-in) |
| Checkpoint registry  | inactive unless an operator initialises one |
| Operator override    | `PHOTON_ACTION_MEMORY_CHECKPOINT` still wins |
| MLX dependency       | optional and lazily imported |
| CI                   | passes with MLX uninstalled and no checkpoint |

## Implemented in this Issue

- `context_pack_ranking_log` (Phase 1)
- `action-memory-feedback.v1` JSONL exporter (Phase 1)
- v2 checkpoint format + sidecar + suppressed_ids (Phase 2)
- `CheckpointRegistry` with atomic `current` / `previous` pointers
  and `promotion_report.json` (Phase 3)
- `/v1/context/pack` ranking modes — `deterministic`, `photon_shadow`,
  `photon_canary`, `photon` (Phase 4)
- `photon_runtime/UPSTREAM.md` slim-port contract (Phase 5)

## Documents

| File | Purpose |
|---|---|
| `feedback-checkpoint-production-ranking-spec.md` | Canonical v0.4.1 contract for Issue #126. |

## Follow-up

- A trained / derived production checkpoint is still required to see a
  PHOTON effect in `photon` mode; the deterministic fallback keeps the
  sidecar safe until that lands.
- The actual slim port of `photon-mlx` modules into
  `photon_action_memory/photon_runtime/` is deliberately deferred — only
  the upstream contract file is shipped today.
