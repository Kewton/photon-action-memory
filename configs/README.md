# Configs

Configuration files for sidecar, evaluation, local LLM draft generation, and
PHOTON checkpoint scorer runs live here when they are safe to commit.

Do not commit local secrets, raw dataset paths, checkpoints, or machine-specific config.

Local-only paths should stay in environment variables instead:

| Variable | Purpose |
|---|---|
| `PHOTON_ACTION_MEMORY_DB` | SQLite event store path. |
| `PHOTON_ACTION_MEMORY_SUMMARY_DB` | SQLite summary store path. |
| `PHOTON_SUMMARY_GENERATOR` | `rule_based` by default; `llm` for opt-in local LLM drafts. |
| `PHOTON_SUMMARY_LLM_MODEL` | Local MLX model identifier/path for the optional draft generator. |
| `PHOTON_ACTION_MEMORY_CHECKPOINT` | Local PHOTON checkpoint path for scorer evaluation. |
