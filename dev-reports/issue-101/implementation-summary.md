# Implementation Summary - Issue #101

## Changes

- Added three Anvil cross-lingual English workdir seed fixtures:
  - `tests/fixtures/shared/anvil_eval_s2_03_en_action_summary.json`
  - `tests/fixtures/shared/anvil_eval_s3_01_en_action_summary.json`
  - `tests/fixtures/shared/anvil_eval_s5_01_en_action_summary.json`
- Updated `scripts/seed_expanded_eval_scenarios.sh` to seed the three new
  fixtures.
- Extended `tests/test_anvil_eval_multilingual_seeds.py` so the new fixtures:
  - validate as `ActionSummary`;
  - keep EN/JA variants for facts, hints, and avoid entries;
  - fit the default context-pack budget;
  - are referenced by the seed script;
  - resolve through exact Anvil-style `repo.name` values:
    `S2-03-en`, `S3-01-en`, and `S5-01-en`.

## Notes

The new fixtures intentionally keep the same task content as the existing
non-`-en` scenario seeds while changing `repo_id` and id fields to match Anvil's
English workdir basenames. This isolates the intended cross-lingual evaluation
variable: JP tasks and EN tasks can now both retrieve photon memory, instead of
the EN side accidentally running with no seed.
