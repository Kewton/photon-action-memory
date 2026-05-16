# Issue #121 — Implementation summary

## What landed

### Phase 1 — Generator contract
- `photon_action_memory/memory/summary_generator.py`:
  `SummaryGeneratorProtocol`, `RuleBasedSummaryGenerator` (wraps the
  existing `ActionSummaryBuilder`; identical behaviour), closed-enum
  `SummaryGeneratorFallbackReason`, `SummaryGeneratorReport`,
  `SummaryGenerationAborted`, and `make_summary_generator()` factory.
- Factory resolves `PHOTON_SUMMARY_GENERATOR` (case-insensitive,
  unknown → rule_based). When `llm` is requested but construction
  fails (missing MLX or model), the factory returns
  `_AlwaysFallbackGenerator` so the call site never has to handle
  construction errors.

### Phase 2 — LLM draft generator
- `photon_action_memory/memory/llm_draft_summary.py`:
  - `LLMDraftConfig` + `build_llm_draft_config(env)` reading the 5 env
    knobs spec'd in the Issue.
  - `SummaryDraftEventFrame` allowlist DTO + `build_event_frame` that
    sanitizes chunk summary and per-event excerpts (≤320 chars) and
    drops any survivor flagged by `has_sensitive_content`.
  - `LLMDraftSummaryGenerator`: lazy MLX import via
    `_load_mlx_generator`; happy path returns `(summary, report)`
    with `generator_used="llm"`. Every failure mode (`mlx_unavailable`,
    `model_unavailable`, `generation_exception`, `empty_output`,
    `invalid_json`, `schema_validation_failed`,
    `quality_gate_rejected`, `fidelity_invalid`) falls back to
    rule-based with the closed-enum reason. `abort` policy raises
    `SummaryGenerationAborted` instead.
  - `_model_present_locally`: best-effort huggingface cache check so
    `load()` is never invoked when the model is not on disk → no
    CI/import-time download.

### Phase 3 — Validation/telemetry wiring
- `photon_action_memory/api/schema_v2.py`: added two optional
  response fields on `SummarizeResponse` (`generator_used`,
  `generator_fallback_reason`) with backwards-compatible defaults
  (`rule_based`, `null`).
- `photon_action_memory/api/server.py`:
  - `create_app(summary_generator=...)` constructor parameter +
    `app.state.summary_generator`.
  - `/v1/summarize` stored-events path: per-chunk generator call with
    `evidence_records`; aggregates reports via
    `_aggregate_generator_reports` (closed-enum reason, status enum:
    `ok` / `fallback_rule_based` / `degraded` / `aborted`).
  - Inline-chunks path: head chunk runs through the generator,
    remaining chunks merged deterministically (preserves evidence
    grounding); telemetry reflects the head report.
  - Pre-existing canonicalizer + answer-leak gate + fidelity checker
    still run on every chunk; LLM output cannot bypass any of them.

### Phase 4 — PHOTON Action Memory scorer
- `photon_action_memory/models/photon_scorer.py`:
  `ActionMemoryPhotonScorer` Protocol with DTOs for summary /
  evidence / next_hint / failed_attempt candidates +
  `ActionMemoryScoreResult` (summary, evidence, next-hint, failure
  similarity scores, optional drift score, model_version, warnings).
- `DeterministicActionMemoryScorer`: pure Jaccard-overlap fallback
  with `model_version="deterministic-overlap-v1"`.
- `PhotonMLXActionMemoryScorer`: thin wrapper around the existing
  `PhotonMLXAdapter._score` boundary. If any `PhotonAdapterError`
  fires mid-scoring, it falls back to the deterministic scorer with
  `warnings=("photon_unavailable",)`.
- `make_action_memory_scorer(env)` factory never raises: missing
  checkpoint env → deterministic; failed adapter construction →
  deterministic with `photon_unavailable` warning.

### Tests
- `tests/test_summary_generator.py` (8 cases) — factory defaults,
  unknown-value fallback, rule-based byte-equivalence with the legacy
  builder, LLM-mode without MLX returning the always-fallback wrapper.
- `tests/test_llm_draft_summary.py` (16 cases) — happy path; every
  fallback enum (`mlx_unavailable`, `model_unavailable`,
  `empty_output`, whitespace-only-empty, `invalid_json`,
  `generation_exception`, `schema_validation_failed`,
  `quality_gate_rejected`); abort policy raises;
  `SummaryDraftEventFrame` drops secrets / home paths / sensitive
  excerpts; prompt JSON has only allowlisted keys; subprocess import
  check confirms `mlx`/`mlx_lm` is not loaded by the module.
- `tests/test_action_memory_scorer.py` (8 cases) — deterministic
  scoring monotonicity for summary/evidence; next-hint and
  failed-attempt presence; model version + drift_score=None; warnings
  propagation; factory deterministic-when-no-checkpoint; factory
  fallback-with-warning on bad checkpoint env; factory never raises.
- `tests/test_summarize_endpoint.py` (2 new cases) — default endpoint
  reports `generator_used="rule_based"`, `fallback_reason=None`; LLM
  mode without MLX reports `rule_based` + closed-enum reason +
  `status="fallback_rule_based"`.

### Reports
- `dev-reports/issue-121/design.md` — pre-implementation design note.
- `dev-reports/issue-121/implementation-summary.md` — this file.
- `dev-reports/issue-121/verification.md` — verification results.

## Files changed

```
photon_action_memory/api/schema_v2.py
photon_action_memory/api/server.py
photon_action_memory/memory/summary_generator.py    (new)
photon_action_memory/memory/llm_draft_summary.py    (new)
photon_action_memory/models/photon_scorer.py        (new)
tests/test_summary_generator.py                     (new)
tests/test_llm_draft_summary.py                     (new)
tests/test_action_memory_scorer.py                  (new)
tests/test_summarize_endpoint.py                    (2 new cases)
dev-reports/issue-121/design.md                     (new)
dev-reports/issue-121/implementation-summary.md     (new)
dev-reports/issue-121/verification.md               (new)
```

## Out of scope (intentionally)

- /v1 endpoint wiring of `ActionMemoryPhotonScorer` into
  `/v1/context/pack` ranking — boundary is in place so a follow-up
  Issue can plug it in.
- Anvil/UAT comparison report between rule-based and LLM seeds (a
  separate v0.4.0 eval Issue).
- `/v1/summarize` firewall-draft path remains unchanged — that path
  is for callers producing LLM output outside the sidecar.
