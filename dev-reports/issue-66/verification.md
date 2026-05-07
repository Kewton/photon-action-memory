# Issue #66 Verification

## Test run

```
python -m pytest tests/test_evidence_expander.py -v
43 passed in 0.37s
```

New tests added (11):
- `test_selected_ids_allows_listed_id`
- `test_selected_ids_omits_unlisted_id`
- `test_selected_ids_none_allows_all`
- `test_selected_ids_partial_filtering`
- `test_anvil_profile_denies_raw_even_when_allow_raw_full_output_true`
- `test_anvil_profile_denies_stderr_even_when_allow_raw_full_output_true`
- `test_anvil_profile_allows_concise_snippet`
- `test_api_stable_reason_not_found`
- `test_api_stable_reason_raw_denied`
- `test_api_stable_reason_anvil_raw_denied`
- `test_api_stable_reason_not_in_selection`

## Full suite

```
python -m pytest --tb=short -q
627 passed, 1 skipped in 2.78s
```

No regressions.
