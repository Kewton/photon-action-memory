# Scripts

Repository-local helper scripts are thin wrappers around importable package
modules under `photon_action_memory/`.

## Sidecar And Anvil Smoke

| Script | Purpose |
|---|---|
| `anvil_v1_summarize_smoke.py` | Drives `/v1/summarize -> /v1/summary/upsert -> /v1/context/pack -> /v1/evidence/expand -> /v1/evaluate` against `127.0.0.1:18765`. |
| `seed_live_injection_summary.py` | Seeds the shared live-injection summary fixture into the local sidecar. |
| `seed_expanded_eval_scenarios.sh` | Seeds the beta/gamma Anvil eval scenario fixtures. |
| `seed_common_seeds.sh` | Seeds common local evaluation summaries. |
| `seed_universal_seeds.sh` | Seeds broader reusable summary fixtures. |

## PHOTON / Evaluation Utilities

| Script | Purpose |
|---|---|
| `build_action_memory_checkpoint.py` | Builds a small Action Memory PHOTON checkpoint from normalized eval/feedback records. |
| `cy5_success_rate_analysis.py` | Computes CY5 success-rate analysis artifacts. |
| `cy6_gate_check.py` | Checks CY6 gate metrics from local eval logs. |

## Orchestration Utilities

| Script | Purpose |
|---|---|
| `codex_orchestrate.py` | Repository-local Codex issue orchestration helper. |
| `commandmate_codex.py` | CommandMate/Codex adapter helper used by orchestration flows. |
