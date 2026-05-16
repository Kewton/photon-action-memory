# Issue #119 Verification

## Focused test

```
$ python -m pytest tests/test_answer_leak.py -v
```

Result: **8 passed, 1 skipped** (the skipped test is the AL-04 layer-B
placeholder).

Test cases:

- `test_answer_leak_patterns_meet_minimum_count` — SSOT contains
  6 patterns including `output_literal_json` and
  `output_key_enumeration`.
- `test_al01_positive_s1_02_fixture_detects_leak` — feeding the
  existing `anvil_eval_s1_02_action_summary.json` to
  `evaluate_summary_quality` yields `status == "warned"` and at least
  one of `output_key_enumeration` / `direct_print_answer` fires on
  `facts[0].text`.
- `test_al02_false_positive_prevention_legitimate_fact_stays_clean` —
  facts like `"summarize.py reads JSON files and validates them"` and
  `"Pytest fixtures live under tests/fixtures/ and load JSON via helpers"`
  stay `clean` (no warnings, no matches).
- `test_detect_answer_leak_returns_one_match_per_pattern` — repeated
  hits of the same pattern within a string are deduplicated to one
  match, keeping the report compact.
- `test_al03_strict_mode_rejects_leaky_seed` — under
  `PHOTON_QUALITY_GATE_MODE=strict` the `/v1/summary/upsert` route
  returns HTTP 422 with `detail.error == "answer_leak_detected"`,
  `detail.summary_id`, and a populated `detail.quality_warnings`.
- `test_al03_warn_mode_annotates_and_persists` — under
  `PHOTON_QUALITY_GATE_MODE=warn` the route responds 200 with
  `status == "stored_with_warnings"`, and the persisted summary
  carries `quality_check_status == "warned"` and non-empty
  `quality_warnings`.
- `test_al03_observe_mode_passes_through` — under
  `PHOTON_QUALITY_GATE_MODE=observe` the route responds 200 with
  `status == "stored"`, the persisted summary keeps
  `quality_check_status == "unchecked"`, and `quality_warnings` stays
  empty (warnings go to the operator log only).
- `test_al03_clean_summary_stored_with_clean_status` — clean
  summaries land as `quality_check_status == "clean"` regardless of
  mode (here under `warn`).
- `test_al04_semantic_similarity_layer_b` — skipped placeholder for
  the layer-B follow-up.

## Related contract tests

```
$ python -m pytest \
    tests/test_summary_store.py \
    tests/test_schema_v2.py \
    tests/test_sidecar_api.py \
    tests/test_anvil_contract.py \
    tests/test_anvil_feedback.py \
    tests/test_anvil_feedback_scoring.py \
    tests/test_summarize_endpoint.py \
    tests/test_contradiction_detection.py \
    tests/test_contradiction_detection_api.py
```

Result: **206 passed**. The new field defaults and the migration leave
all existing contract behaviour intact.

## Full suite

```
$ python -m pytest
```

Result: **1011 passed, 2 skipped, 2 warnings** in ~14s. The two
skipped tests are the pre-existing MLX smoke (opt-in) and the AL-04
layer-B placeholder added by this issue.

## Lint, format, type-check

```
$ python -m ruff check photon_action_memory/governance/answer_leak.py \
    photon_action_memory/api/server.py \
    photon_action_memory/api/schema_v2.py \
    photon_action_memory/memory/summary_store.py \
    photon_action_memory/ranking/feedback.py \
    tests/test_answer_leak.py
All checks passed!

$ python -m ruff format --check ...   # all modified files formatted
$ python -m mypy <modified files>     # Success: no issues found in 5 source files
```

## Manual sanity — strict-mode rejection shape

Hand-checked via the `test_al03_strict_mode_rejects_leaky_seed` test
that the strict-mode response shape is:

```jsonc
{
  "detail": {
    "error": "answer_leak_detected",
    "summary_id": "leaky-sum-001",
    "quality_warnings": [
      "facts[0].text: direct_print_answer: 'prints a JSON object with'",
      "facts[0].text: output_key_enumeration: 'keys alpha, beta, and total'"
    ]
  }
}
```

## Risks / things to watch

- **Pattern drift.** Tightening any pattern (e.g. `direct_print_answer`)
  while production traffic is in `warn` mode could increase the
  warned-seed count and attenuate retrieval scores. Recommended
  rollout order: stay on `warn` for at least one Anvil eval cycle,
  read the Anvil S1-family pass rate, then either flip to `strict` or
  loosen the patterns.
- **Layer-B follow-up.** Layer A only catches lexical answer leaks.
  Paraphrased leaks (e.g. JSON answer written in Japanese only) will
  pass A — the S1-02 Japanese fact intentionally bypasses
  `output_key_enumeration` today because the English fact already
  trips the gate.
- **Migration safety.** The migration is purely additive (`ALTER
  TABLE ... ADD COLUMN ... NOT NULL DEFAULT 'unchecked'`) and creates
  an index afterwards. Existing rows are unaffected. Rolling back to a
  pre-#119 binary leaves the extra column in place — readers ignore
  it (older schema `_initialize_schema` only declares the columns it
  knows).
