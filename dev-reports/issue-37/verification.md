# Issue #37 Verification

## Commands run and results

### `python -m ruff format --check .`
```
55 files already formatted
```
Exit code: 0 - PASS

### `python -m ruff check .`
```
All checks passed!
```
Exit code: 0 - PASS

### `python -m mypy photon_action_memory tests`
```
Success: no issues found in 53 source files
```
Exit code: 0 - PASS

### `python -m pytest -q`
```
s.......................................................................
.......................................................................
.......................................................................
.......................................................................
...........................................
1 skipped (MLX smoke is opt-in), 330 passed in 1.20s
```
Exit code: 0 - PASS

---

## Acceptance criteria checklist

| Criterion | Test(s) | Result |
|---|---|---|
| raw tool stdout/stderr not in ContextPack items | `test_stdout_is_denied`, `test_stderr_is_denied`, `test_raw_items_not_in_pack_items` | PASS |
| full grep output denied | `test_grep_output_is_denied` | PASS |
| full build log denied | `test_build_log_is_denied` | PASS |
| full file content denied | `test_file_content_is_denied` | PASS |
| secret-like string not prompt-visible | `test_secret_kv_pair_detected`, `test_secret_in_raw_item_does_not_reach_items`, `test_api_secret_in_raw_evidence_is_denied` | PASS |
| absolute home path not prompt-visible | `test_absolute_home_path_detected`, `test_home_path_in_unknown_kind_is_denied` | PASS |
| token-like value not prompt-visible | `test_openai_style_token_detected`, `test_github_pat_detected`, `test_bearer_token_detected` | PASS |
| denied items in omitted with reasons | `test_raw_items_appear_in_omitted`, `test_raw_items_omitted_with_reasons` | PASS |
| policy tests verify raw_tool_tokens_in_prompt is approximately 0 | `test_raw_tool_tokens_in_prompt_is_zero_with_only_raw_items`, `test_raw_tool_tokens_in_prompt_zero_mixed_with_summaries` | PASS |
| admission decisions record deny with policy | `test_raw_items_produce_deny_decisions`, `test_raw_decision_has_policy_field`, `test_api_raw_evidence_deny_decisions_have_policy` | PASS |
| existing tests still pass (no regression) | all 302 pre-existing tests | PASS |
