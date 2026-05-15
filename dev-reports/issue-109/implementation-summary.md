# Issue #109 Implementation Summary

## Changes

- Added `COMMON_REPO_ID = "__common__"` and `SummaryRetriever.search_common()`.
- Added `merge_dedup_summaries()` for deterministic specific-first merging.
- Updated `_resolve_context_summaries()` to append common seeds by
  `task_signature`.
- Added three common seed fixtures and a common seed script.
- Added context-pack API tests for:
  - repo-specific + common simultaneous retrieval,
  - common fallback when repo has no match,
  - common seed skip under token budget pressure,
  - summary-id dedup with specific precedence.

## Compatibility

Explicit candidate IDs retain the old behavior. Existing repo-specific
retrieval keeps its order and only gains same-task common seeds after the
specific results.
