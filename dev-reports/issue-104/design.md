# Design Note - Issue #104

## Goal

Improve the Japanese variants in Anvil eval seed fixtures so JP tasks can use
the same guidance as EN tasks without losing concrete action details.

## Approach

- Update only `lang="ja"` entries in the original seven expanded eval fixtures:
  `S1-02`, `S2-03`, `S3-01`, `S3-03`, `S3-04`, `S5-01`, and `S6-04`.
- Preserve all English `lang="en"` entries unchanged.
- Keep code identifiers, file names, commands, and exact replacement snippets in
  ASCII so the LLM can align them with repository files and verifier output.
- Prefer concise imperative/note style:
  - `tool.py の double(x) を修正。return ... を return ... に変更。`
  - `検証は python3 custom_check.py。pytest は使わない。`
- Add fixture tests that lock important JP phrases for the seven updated seeds.

## Verification Plan

- Run multilingual seed fixture tests.
- Run shared fixture tests.
- Run ruff and mypy.
- Note that full Anvil cross-lingual evaluation is outside this repository and
  remains a follow-up validation step.
