# Issue #110 Implementation Summary

## Changes

- New `photon_action_memory/governance/` package with a pure-function
  `contradiction.detect_contradictions()` that compares
  `ActionSummary` seeds within the same `repo_id + task_signature`
  scope and returns `ContradictionPair` records.
- Five syntax-based detection rules: `avoid_vs_action`,
  `avoid_polarity_conflict`, `fact_negation`, `next_hint_conflict`,
  `failed_attempt_vs_next_hint`.
- `ValidityStatusKind` extended with `"needs_review"`; scoring weights
  in `models/context_scorer.py` updated so the new status sits between
  `partial` and `stale`.
- New `POST /v1/seeds/audit/contradictions` endpoint and
  `ContradictionAuditRequest` / `ContradictionAuditResponse` /
  `ContradictionPairModel` schemas.
- `_resolve_context_summaries` runs detection on the resolved seed set
  and emits `ContextPackWarning(kind="contradiction_detected", …)`
  entries before pack assembly.
- New `photon_action_memory/cli/audit.py` with the `photon-audit
  detect-contradictions` subcommand and a matching console script in
  `pyproject.toml`.

## Tests

- `tests/test_contradiction_detection.py` — 16 unit cases covering the
  five detection rules, scope filtering, dedup, and the
  `ContradictionPair` API.
- `tests/test_contradiction_detection_api.py` — 7 integration cases:
  audit endpoint output, context-pack warning emission, the
  `needs_review` keep-warning path, the `contradicted` suppression
  path, and CLI payload generation.

## Compatibility

- Existing seeds default to `applicability_scope="repo"` and
  `validity.status="valid"` — no behaviour change for already-stored
  data.
- The new `needs_review` status is recoverable through
  `SummaryRetriever` (it is not in `_STALE_STATUSES`), so seeds keep
  being retrieved while the contradiction warning surfaces them for
  review.
- `_resolve_context_summaries` only adds detection at the final stage;
  the existing universal/common/specific retrieval order is unchanged.
