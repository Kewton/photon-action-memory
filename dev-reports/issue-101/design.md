# Design Note - Issue #101

## Goal

Anvil's `cross_lingual` scenario set uses workdir basenames as photon `repo_id`
values. The English variants use `S2-03-en`, `S3-01-en`, and `S5-01-en`, while
the current photon seed fixtures only cover `S2-03`, `S3-01`, and `S5-01`.

Add seed fixtures for the three English workdir names so `/v1/context/pack`
retrieval can exercise photon injection for both the JP and EN sides of the
scenario pair.

## Approach

- Add three ActionSummary fixtures under `tests/fixtures/shared/`:
  - `anvil_eval_s2_03_en_action_summary.json`
  - `anvil_eval_s3_01_en_action_summary.json`
  - `anvil_eval_s5_01_en_action_summary.json`
- Keep the existing scenario content and bilingual `lang=en/ja` facts and hints,
  but change `repo_id`, `summary_id`, `session_id`, chunk ids, and evidence ids
  to the `*-en` scenario names.
- Register the fixtures in `scripts/seed_expanded_eval_scenarios.sh`.
- Extend fixture tests so the new files validate as `ActionSummary`, fit the
  context-pack budget, are referenced by the seed script, and are retrievable
  through an exact `repo_id` match.

## Verification

- Focused pytest for the seed fixture suite.
- Script dry-run for each new fixture through `seed_live_injection_summary.py`.
- Local sidecar smoke: upsert the new fixtures and confirm `/v1/context/pack`
  returns an admitted item for `S2-03-en`, `S3-01-en`, and `S5-01-en`.
