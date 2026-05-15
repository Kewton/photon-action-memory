# Implementation Summary - Issue #104

## Changes

- Rewrote Japanese `facts` / `next_hints` wording in the original seven Anvil
  expanded eval seed fixtures:
  - S1-02
  - S2-03
  - S3-01
  - S3-03
  - S3-04
  - S5-01
  - S6-04
- Preserved all existing English `lang="en"` entries.
- Kept file names, command names, verifier names, and code replacements in
  ASCII to improve task/seed alignment in JP prompts.
- Added JP phrase regression tests so future edits keep the most actionable
  terms prompt-visible.

## Notes

S5-01 now states the core verifier rule directly in Japanese:
`検証は python3 custom_check.py。pytest では検証しない。`
This is the scenario with the largest observed JP/EN pass gap.
