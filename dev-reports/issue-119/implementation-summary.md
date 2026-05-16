# Issue #119 Implementation Summary — Answer-leak quality gate

## Outcome

`POST /v1/summary/upsert` now runs a pure-function answer-leak gate on
every `ActionSummary` before persisting it. Behaviour is selected by
`PHOTON_QUALITY_GATE_MODE` (`strict` / `warn` / `observe`; default
`warn`). Detected leaks land in `ActionSummary.quality_warnings` and
`ActionSummary.quality_check_status`, are persisted via a backwards-
compatible SQLite migration, and attenuate retrieval scores via
`FeedbackAdjustedContextScorer`.

## Files changed

### New
- `photon_action_memory/governance/answer_leak.py` — pure-function
  module exposing `ANSWER_LEAK_PATTERNS` (regex SSOT, 6 entries),
  `LeakMatch`, `QualityReport`, `detect_answer_leak`, and
  `evaluate_summary_quality`.
- `tests/test_answer_leak.py` — AL-01 / AL-02 / AL-03 / AL-04
  regression tests plus pattern-count and per-pattern dedup checks.
- `dev-reports/issue-119/design.md`,
  `dev-reports/issue-119/implementation-summary.md`,
  `dev-reports/issue-119/verification.md`.

### Modified
- `photon_action_memory/api/schema_v2.py` — adds
  `QualityCheckStatus` literal and the
  `ActionSummary.quality_warnings` / `quality_check_status` fields
  (defaults preserve backwards compatibility).
- `photon_action_memory/api/server.py` — wires the gate into
  `upsert_summary` via `_apply_answer_leak_gate`, with the
  `PHOTON_QUALITY_GATE_MODE` resolver.
- `photon_action_memory/memory/summary_store.py` — adds the
  `quality_check_status` column to fresh schemas, includes a
  `PRAGMA table_info`-driven `ALTER TABLE` migration for existing DBs,
  and threads the value through `upsert`.
- `photon_action_memory/ranking/feedback.py` — adds
  `QUALITY_WARNED_FACTOR = 0.5` and applies the attenuation in
  `apply_feedback_boost` plus the admission and usefulness scoring
  paths of `FeedbackAdjustedContextScorer`.
- `docs/photon-action-memory.md` — documents the new env var,
  pattern table, response statuses, and DB migration note.

## Key design decisions

- **Pure function vs route decision.** `evaluate_summary_quality`
  itself only emits `clean` / `warned`. The strict-mode `rejected`
  decision lives in the route wrapper so the pure function stays
  agnostic of HTTP semantics and the wrapper is the single owner of
  the env-var policy.
- **`unchecked` over `clean` for legacy rows.** The migration default
  is `"unchecked"` rather than `"clean"` so seeds that pre-date the
  gate are not silently relabelled. The retrieval-side attenuation
  only triggers on `"warned"`, so `unchecked` rows behave exactly as
  before — no surprise re-ranking.
- **Conservative regex set.** Each pattern was validated against the
  S1-02 fixture (positive) and the "summarize.py reads JSON files"
  AL-02 case (negative). `direct_print_answer` restricts the verb
  list (`prints / outputs / returns / shows / emits / writes`) so
  read-only verbs (`reads / parses / validates`) do not trip.
- **Observe-mode pass-through.** Observe leaves the persisted summary
  unchanged so a re-upsert during a calibration window can't silently
  relabel a previously-stored seed. Warnings still hit the operator
  log so impact can be measured.
- **Backwards-compatible migration.** The `_initialize_schema` now
  reads `PRAGMA table_info(action_summaries)` and only `ALTER TABLE`s
  when the column is missing. The new `idx_summaries_quality` index
  is created *after* the migration so it works on both fresh and
  migrated databases.

## Acceptance criteria coverage

| Criterion | Coverage |
|---|---|
| `governance/answer_leak.py` new module (pure) | `photon_action_memory/governance/answer_leak.py` |
| 6+ regex patterns in `ANSWER_LEAK_PATTERNS` | 6 patterns; asserted in `test_answer_leak_patterns_meet_minimum_count` |
| `detect_answer_leak(text)` pure function | implemented |
| `evaluate_summary_quality(summary)` aggregator | implemented |
| `server.py::summary_upsert` quality gate | implemented via `_apply_answer_leak_gate` |
| `PHOTON_QUALITY_GATE_MODE` strict/warn/observe (default warn) | implemented, AL-03 tests cover all 3 |
| `ActionSummary.quality_warnings` / `quality_check_status` (backwards-compatible defaults) | added with `default_factory=list` / `"unchecked"` |
| DB schema migration | additive column + `ALTER TABLE` migration, index added post-migration |
| `FeedbackAdjustedContextScorer` attenuates warned seeds | `QUALITY_WARNED_FACTOR = 0.5` in `apply_feedback_boost`; threaded through admission + usefulness scoring |
| `tests/test_answer_leak.py` regression coverage | AL-01 / AL-02 / AL-03 covered; AL-04 reserved with `pytest.skip` (layer B follow-up) |
| Docs update | `docs/photon-action-memory.md` Answer-leak Quality Gate section added |

## Deferred / follow-ups

- **AL-04 / Layer B (semantic similarity).** Out of scope for #119;
  the test slot is reserved with a `pytest.skip`. A follow-up issue
  should add an embedding-based check (likely reusing the existing
  `overlap_detector` embedding mode) for cases where the leak is
  paraphrased.
- **Backfill of `quality_check_status` on existing rows.** The column
  defaults to `"unchecked"` on migration; a one-shot batch job that
  re-runs the gate over already-stored seeds is a follow-up so the
  attenuation can apply to legacy data.
- **`aggregate_anvil_feedback` extension.** The acceptance criterion
  also names `aggregate_anvil_feedback` for attenuation. We chose to
  do the attenuation at the scorer (the only consumer that actually
  ranks summaries against each other) rather than mutate the pack-
  level aggregate, which is shared with multiple downstream features.
  If a future use case needs the aggregate-level signal, the scorer's
  `_quality_check_status` helper is the natural extraction point.
