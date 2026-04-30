# Issue 6 Design

## Goal

Implement the no-model deterministic ranking path used by `/v1/suggest` so the sidecar can return stable, bounded suggestions when PHOTON scoring is unavailable.

## Approach

- Keep the public schema unchanged.
- Extract file path candidates from touched files, recent event metadata, and recent event summaries.
- Score candidates with deterministic integer signals:
  - recent error file paths first;
  - touched files and explicit target/path metadata next;
  - stable first-seen order as the tie breaker.
- Generate only low-risk `read`, `inspect`, `search`, and optional test/build suggestions; filter destructive shell commands.
- Keep evidence generation bounded by `budget.max_evidence_chars` and suggestions bounded by `budget.max_suggestions`.
- Add guard helpers for repeated read/search warnings, missing evidence warnings for edit-like requests, and destructive command filtering.

## Test Plan

- Add focused ranking and guard tests for deterministic ordering, recent error priority, warning triggers, evidence budgeting, and destructive command filtering.
- Update sidecar API tests to cover the delegated fallback path.
- Run focused tests first, then the full pytest suite and static checks if practical.
