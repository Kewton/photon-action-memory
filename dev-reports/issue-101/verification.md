# Verification - Issue #101

## Automated Checks

- `python -m pytest tests/test_anvil_eval_multilingual_seeds.py -q`
  - PASS: 52 passed
- `python -m pytest tests/test_anvil_eval_multilingual_seeds.py tests/test_shared_fixtures.py -q`
  - PASS: 62 passed
- `python -m ruff format --check .`
  - PASS: 101 files already formatted
- `python -m ruff check .`
  - PASS: All checks passed
- `python -m mypy photon_action_memory tests`
  - PASS: no issues found in 95 source files

## Seed Dry Run

Validated `seed_live_injection_summary.py --dry-run` for:

- `anvil_eval_s2_03_en_action_summary.json`
- `anvil_eval_s3_01_en_action_summary.json`
- `anvil_eval_s5_01_en_action_summary.json`

Each dry run emitted an `/v1/summary/upsert` payload with the expected
`repo_id` and request id.

## Curl Smoke

Started a temporary sidecar from this branch on `127.0.0.1:18767` with isolated
SQLite files:

- `/tmp/photon-action-memory-issue-101-events.sqlite`
- `/tmp/photon-action-memory-issue-101-summaries.sqlite`

Seeded the three new fixtures, then called `/v1/context/pack` with Anvil-style
repo names:

| repo_id | result |
| --- | --- |
| `S2-03-en` | `sidecar_status=ok`, item `anvil-eval-s2-03-en-svelte-001`, decision `admit` |
| `S3-01-en` | `sidecar_status=ok`, item `anvil-eval-s3-01-en-calculator-001`, decision `admit` |
| `S5-01-en` | `sidecar_status=ok`, item `anvil-eval-s5-01-en-tool-double-001`, decision `admit` |

The temporary sidecar process was stopped after verification.
