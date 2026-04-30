# Issue #8 Design

## Scope

Add the first concrete dataset utility layer for sanitized trajectory examples:

- a JSONL-compatible record shape with the required top-level fields
- deterministic train / val / test splitting based on stable example IDs
- aggregate stats for action, tool, CLI command, target files, and redaction counters
- focused fixture coverage for split determinism, stats, JSONL round-trip, and redaction linkage

## Design

`photon_action_memory/training/datasets.py` will expose a small standard-library API:

- `DatasetRecord` validates and serializes records with `example_id`, `schema_version`, `source`, `task`, `state`, `label`, `quality`, and `redaction`.
- `make_dataset_record` creates a record and derives a deterministic `example_id` from canonical JSON when one is not supplied.
- `split_records` assigns records to train / val / test by sorting SHA-256 keys made from `seed` and `example_id`, then allocating ratio-based counts.
- `dataset_stats` returns JSON-safe counters for actions, tools, CLI commands, target files, and redaction totals.
- JSONL helpers write and read records without changing the embedded `redaction` payload, so split files remain linked to the original redaction report metadata.

The code avoids exporter-specific assumptions. It accepts common field names in `label`, `state`, and `source` for stats extraction, which keeps the API useful for current fixtures and future exporter work without creating a broader exporter implementation in this issue.
