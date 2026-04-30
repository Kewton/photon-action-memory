# Issue 6 Implementation Summary

## Changed

- Added deterministic file path extraction in `ranking/candidates.py`.
- Implemented fallback suggestion ranking in `ranking/fallback.py`:
  - stable first-seen tie breaking;
  - recent error file paths ranked above ordinary touched files;
  - basename matches canonicalized back to touched full paths;
  - bounded suggestion output;
  - safe test/build command suggestions and search fallback.
- Implemented guard helpers in `ranking/guards.py`:
  - `model_unavailable` fallback warning;
  - repeated read/search warning detection;
  - missing evidence warning for edit-like requests;
  - destructive shell command detection.
- Updated `/v1/suggest` to delegate fallback suggestion building and warnings to ranking modules.
- Marked the Issue #6 Phase 4 checklist items complete in the development preparation plan.
- Added focused tests in `tests/test_ranking_fallback.py`.

## Notes

- The API schema was not changed.
- The fallback path still returns the existing fallback model version when the PHOTON model is unavailable.
- Evidence remains sourced from recent events and capped by `budget.max_evidence_chars`.
