# Issue #109 Design

## Goal

Add a repo-agnostic common seed layer so context retrieval can return useful
generic knowledge when a repo-specific seed is missing or too narrow.

## Retrieval Order

`_resolve_context_summaries()` now resolves candidates in this order:

1. Explicit `candidate_summary_ids` still bypass auto search.
2. Repo-specific `(repo_id, task_signature)` matches.
3. Repo-specific `repo_id` matches when stage 2 found nothing.
4. Common seeds with `repo_id="__common__"` and the same `task_signature`.

The merge helper deduplicates by `summary_id` while preserving earlier results,
so repo-specific summaries always win over common summaries. Because common
seeds are appended after repo-specific results, normal context-pack admission
also makes repo-specific seeds win token-budget competition.

## Seed Samples

Common seed fixtures are stored under `tests/fixtures/shared/`:

- `common_pytest_action_summary.json`
- `common_rust_error_handling_action_summary.json`
- `common_sveltekit_vs_react_action_summary.json`

`scripts/seed_common_seeds.sh` seeds them, and
`scripts/seed_expanded_eval_scenarios.sh` invokes that helper after the
existing Anvil eval seed set.

## Out of Scope

- Universal scope retrieval. Issue #111 adds that as Stage 4.
- Semantic or embedding-based common retrieval.
- Anvil A/B eval measurement. The issue tracks that as a separate phase.
