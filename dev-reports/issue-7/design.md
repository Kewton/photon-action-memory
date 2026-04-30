# Issue 7 Design

## Scope

Migrate the MyCodeBranchDesk SQLite exporter from
`photon-mlx-develop/scripts/export_agent_training_data.py` into importable
`photon_action_memory` modules instead of copying the single script shape.

## Module Split

- `photon_action_memory.training.labels`
  - tool call extraction from assistant text and prompt metadata
  - next action classification
  - safe file path candidate extraction for target/evidence labels
- `photon_action_memory.training.datasets`
  - stable IDs/hashes
  - canonical JSONL writing
  - redaction report writing
- `photon_action_memory.training.exporters.mycodebranchdesk`
  - read-only MyCodeBranchDesk SQLite access
  - session grouping and example construction
  - CLI-compatible export options and stats

## Safety Choices

- Reuse `memory.sanitizer` for all text/path sanitization.
- Do not expose the raw DB path in examples or reports; store only a stable
  hash plus non-local metadata.
- Do not dump full raw conversation logs. By default the assistant text label
  field stays empty, and context is summarized from sanitized summaries/content.
- Keep the fixture test synthetic so no raw local database is committed.

## Verification Plan

- Add focused unit tests that create a temporary MyCodeBranchDesk-like SQLite
  database, export JSONL and a redaction report, and assert:
  - a next action label is produced
  - target file and useful evidence labels are present
  - secrets, emails, and raw absolute paths are not emitted
  - source metadata contains `db_path_hash` but not the raw DB path
