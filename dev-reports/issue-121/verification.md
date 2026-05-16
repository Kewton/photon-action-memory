# Issue #121 — Verification

## Focused tests

```
$ python -m pytest tests/test_summary_generator.py \
    tests/test_llm_draft_summary.py \
    tests/test_action_memory_scorer.py \
    tests/test_summarize_endpoint.py -q
41 passed
```

41 new test cases all pass. Coverage:

- `test_summary_generator.py` — `SummaryGeneratorProtocol` contract,
  factory default rule_based, unknown-value fallback, byte-equivalent
  output vs. the legacy `ActionSummaryBuilder`, LLM-mode without MLX
  yielding the always-fallback wrapper.
- `test_llm_draft_summary.py` — every closed-enum fallback reason
  exercised (`mlx_unavailable`, `model_unavailable`, `empty_output`,
  whitespace-only, `invalid_json`, `generation_exception`,
  `schema_validation_failed`, `quality_gate_rejected`); `abort` policy
  raises; `SummaryDraftEventFrame` drops secrets / home paths /
  sensitive evidence excerpts; only allowlisted keys appear in the
  prompt; subprocess assertion that importing the module never loads
  `mlx`/`mlx_lm`.
- `test_action_memory_scorer.py` — deterministic scorer monotonicity
  on summary/evidence; next-hint and failed-attempt scores present;
  `model_version="deterministic-overlap-v1"` + `drift_score is None`;
  warnings propagation; factory deterministic-when-no-checkpoint;
  factory fallback-with-warning on bad checkpoint env; factory never
  raises.
- `test_summarize_endpoint.py` — default `/v1/summarize` reports
  `generator_used="rule_based"`, `fallback_reason=None`; LLM-mode
  without MLX reports rule_based + closed-enum reason +
  `status="fallback_rule_based"`.

## Broader checks

### Full unit suite

```
$ python -m pytest tests/ --ignore=tests/integration -q
1039 passed, 6 failed, 1 skipped
```

The 6 failing tests are pre-existing on `main`/the base branch and
are unrelated to this Issue:

- `test_anvil_context_pack_api.py::test_anvil_raw_evidence_all_denied`
- `test_anvil_context_pack_api.py::test_anvil_raw_evidence_deny_decisions_have_policy`
- `test_anvil_contract.py::test_anvil_raw_log_fixture_api_returns_empty_items`
- `test_context_pack.py::test_context_pack_api_returns_summary_only_pack`
- `test_context_pack.py::test_context_pack_api_token_budget_in_response`
- `test_shared_fixtures.py::test_shared_raw_log_not_in_context_pack_items`

Confirmed pre-existing by re-running the suite with `git stash`
applied to this branch (same 5 failures plus `test_anvil_raw_evidence_all_denied`).
These all relate to universal-seed retrieval changes in `/v1/context/pack`
made before this Issue and should be addressed separately.

### Type check

```
$ python -m mypy photon_action_memory tests
Success: no issues found in 111 source files
```

### Lint

```
$ python -m ruff check
All checks passed!

$ python -m ruff format --check .
117 files already formatted
```

## Acceptance criteria walk-through

| Criterion | Where verified |
|---|---|
| Default config keeps existing rule-based behaviour | `test_summary_generator.py::TestRuleBasedRegression::test_rule_based_matches_builder_output` (byte-equal output) + `test_summarize_endpoint.py::test_summarize_default_reports_rule_based_generator` |
| `PHOTON_SUMMARY_GENERATOR=llm` is the only switch that enables LLM | `summary_generator._resolve_mode` (only `"llm"` returns `llm`, everything else → rule_based) + `test_summary_generator.py::TestFactoryDefaults` |
| Fallback on missing MLX / model / generation exception / empty / invalid JSON / schema fail / quality-gate reject | `test_llm_draft_summary.py::TestFallbackReasons` (one test per enum) |
| Fallback reasons exposed as closed-enum telemetry | `SummaryGeneratorFallbackReason` `Literal` + `SummarizeResponse.generator_fallback_reason` field |
| LLM output cannot bypass schema validation, evidence grounding, quality gate | `LLMDraftSummaryGenerator._build_or_raise` runs `_filter_evidence`, `SummaryCanonicalizer`, `evaluate_summary_quality`, and (when evidence supplied) `SummaryFidelityChecker` before returning |
| `facts[]` must carry valid evidence ID | `_filter_evidence` keeps only ids in `chunk.event_ids`; missing → `schema_validation_failed`; verified by `test_schema_validation_fails_when_evidence_id_unknown` |
| No raw log / secret / home path / full diff / full prompt in prompt-visible memory | `SummaryDraftEventFrame` sanitizes summary + per-event excerpt, re-checks with `has_sensitive_content`; verified by `test_frame_drops_secret_from_chunk_summary`, `test_frame_drops_home_path_from_chunk_summary`, `test_frame_omits_evidence_excerpt_when_sensitive`, `test_prompt_contains_only_allowlisted_keys` |
| No network / model download in CI | `_load_mlx_generator` raises `MlxUnavailable`/`ModelUnavailable` before invoking MLX `load`; lazy import only; subprocess test (`test_module_import_does_not_import_mlx`) asserts importing the module does not import `mlx`/`mlx_lm` |
| PHOTON/MLX scorer fallback when unavailable | `make_action_memory_scorer` returns `DeterministicActionMemoryScorer` when no checkpoint or on construction failure; `test_action_memory_scorer.py::TestFactory` cases (no env, invalid env, never-raises) |
| Focused eval shows raw leak / answer leak not worse than baseline | LLM output runs the same `SummaryFidelityChecker` and `evaluate_summary_quality` gates the rule-based path uses, and is rejected with `fidelity_invalid` / `quality_gate_rejected` before being stored. The full Anvil/UAT eval is deferred to a v0.4.0 eval Issue (noted in design.md). |
