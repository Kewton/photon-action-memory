# photon_runtime — upstream contract

This file documents the **slim port boundary** between this repository and
[`photon-mlx`](https://github.com/kewton/photon-mlx-develop). It is the
canonical record consulted by Issue #126 acceptance criteria and any future
sync from upstream.

## Upstream source

| Field | Value |
|---|---|
| Repository | `github.com/kewton/photon-mlx-develop` |
| Local path during port | `/Users/maenokota/share/work/github_kewton/photon-mlx-develop` |
| Upstream commit | `3426681b3e89e897bcbae70995bbfc18a29da82c` |
| Upstream license | MIT (see upstream `LICENSE`) |
| Local license     | MIT (this repo `LICENSE`) — compatible |

## Port status

**No upstream files have been slim-ported into this directory yet.** The
`photon_runtime/` package exists today as a contract marker:

- `photon_action_memory.models.photon_adapter.PhotonMLXAdapter` still
  imports `mlx.core` lazily via `importlib.import_module`. That keeps MLX
  optional and CI green without an MLX install.
- A v2 checkpoint may include a `photon_runtime/` subdirectory (built via
  `write_action_memory_checkpoint(include_photon_runtime_stub=True)`). The
  loader records `PhotonCheckpoint.has_photon_runtime=True` so a future
  port can branch on the presence of bundled runtime weights without
  changing the public API.

## Files reserved for slim port

When the slim port lands, exactly these upstream files should be copied,
mirroring the names from the upstream `photon_mlx/` package:

| Upstream file (`photon_mlx/`) | Local target (`photon_runtime/`) | Purpose |
|---|---|---|
| `checkpoint.py` | `checkpoint.py` | Runtime checkpoint I/O for the scorer. |
| `model.py`      | `model.py`      | Minimal model class used by the scorer. |
| `blocks.py`     | `blocks.py`     | Transformer block primitives. |
| `inference.py`  | `inference.py`  | Scoring forward pass. |
| `session.py`    | `session.py`    | Session-scoped state batching. |
| `trainer.py`    | `trainer.py`    | Offline fine-tune entrypoint (CI never invokes). |
| `loss.py`       | `loss.py`       | Loss functions used by the trainer. |
| `optimize.py`   | `optimize.py`  | Optimiser configuration helpers. |

No other upstream module is in scope. Anything additional pulled in during a
sync must be explicitly added to this table together with its justification.

## Local changes policy

Any deviation from the upstream copy MUST be:

1. Annotated with a `# photon-action-memory: local change ...` comment at
   the point of the deviation.
2. Recorded in the **Local changes** section of this file with a one-line
   summary, the date (UTC ISO-8601), and the rationale.
3. Re-applied during the next sync; the sync script (TBD) reports any
   local change that no longer applies cleanly so reviewers notice drift.

### Local changes

_None yet — directory is intentionally empty._

## MLX import policy

- `import photon_action_memory` MUST NOT import `mlx` or `mlx.core`.
- Any module under `photon_action_memory/photon_runtime/` that requires
  `mlx` MUST import it lazily inside a function body, never at module
  import time, so CI without MLX continues to pass.
- `PhotonMLXAdapter._import_mlx_core` is the single supported entry point
  for resolving `mlx.core`; new code MUST reuse it.

## Sync policy

- Sync direction is upstream → this repo only. We never push from here.
- A sync is performed by running the (future) `scripts/sync_photon_runtime.py`
  tool, reviewing its diff, updating the **Upstream commit** field above,
  and adding a corresponding entry to `CHANGELOG.md` under the active
  release line.
- The sync script must not pull non-source artefacts (tests with large
  fixtures, docs, datasets, etc.) — copy only the files listed in
  **Files reserved for slim port**.

## Verification

- `python -m pytest tests/test_photon_adapter.py tests/test_action_memory_scorer.py -q`
  must continue to pass with MLX uninstalled.
- A v2 checkpoint built with `include_photon_runtime_stub=True` must load
  cleanly via `load_checkpoint_manifest`.
- `PHOTON_ACTION_MEMORY_CHECKPOINT` pointing at such a checkpoint must
  continue to fail-open to deterministic scoring when MLX is missing.
