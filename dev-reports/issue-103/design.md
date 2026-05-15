# Design Note - Issue #103

## Goal

Make the multilingual quality gate emit `premature_termination_risk` for
realistic Anvil cross-lingual S2-03 tasks, not only for near-duplicate curl
smoke prompts.

## Approach

- Replace the hard-coded direct next-hint overlap threshold with a configurable
  helper.
- Default the threshold to `0.15`, low enough to catch the observed realistic
  Anvil S2-03 JP/EN task wording.
- Allow runtime tuning through `PHOTON_PREMATURE_OVERLAP_THRESHOLD`.
- Keep false positives down by exempting concrete code-replacement hints from
  premature-termination warnings. These hints carry specific implementation
  evidence, unlike the S2-03 generic "add an interactive element" hint.
- Do not emit premature-termination warnings for meta/verifier summaries such
  as S5-01, because Anvil should continue to consume verifier guidance.

## Verification Plan

- Add focused tests for:
  - realistic S2-03 JP task warning emission;
  - realistic S2-03 EN task warning emission;
  - S5-01 meta seed remaining admitted with no warning;
  - S3-01 concrete code replacement remaining admitted with no warning;
  - environment override for the threshold.
- Run focused context-pack and overlap detector tests, then ruff and mypy.
