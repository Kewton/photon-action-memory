"""Summary retrieval with staleness filtering."""

from __future__ import annotations

from photon_action_memory.api.schema_v2 import ActionSummary
from photon_action_memory.memory.staleness import StalenessContext, StalenessGuard
from photon_action_memory.memory.summary_store import SummaryStore

COMMON_REPO_ID = "__common__"
_STALE_STATUSES: frozenset[str] = frozenset({"stale", "contradicted"})


class SummaryRetriever:
    """Resolve and filter ActionSummary objects from a SummaryStore.

    Summaries whose validity is already marked stale or contradicted are
    excluded before they reach the ContextPack admission pipeline.
    When a StalenessContext is supplied the StalenessGuard is applied first
    so that context-aware signals (commit change, refuted claims, …) are
    evaluated in addition to the stored validity status.
    """

    def __init__(self, store: SummaryStore) -> None:
        self._store = store
        self._guard = StalenessGuard()

    def resolve_candidates(
        self,
        summary_ids: list[str],
        *,
        staleness_context: StalenessContext | None = None,
    ) -> list[ActionSummary]:
        """Return fresh summaries for the given IDs; missing / stale IDs are skipped."""
        summaries = self._store.resolve(summary_ids)
        return self._filter_stale(summaries, staleness_context)

    def search(
        self,
        *,
        repo_id: str | None = None,
        task_signature: str | None = None,
        staleness_context: StalenessContext | None = None,
        limit: int = 50,
    ) -> list[ActionSummary]:
        """Search by repo/task, then apply staleness filtering."""
        summaries = self._store.search(
            repo_id=repo_id,
            task_signature=task_signature,
            limit=limit,
        )
        return self._filter_stale(summaries, staleness_context)

    def search_common(
        self,
        *,
        task_signature: str,
        staleness_context: StalenessContext | None = None,
        limit: int = 50,
    ) -> list[ActionSummary]:
        """Search common seeds for a task signature."""
        return self.search(
            repo_id=COMMON_REPO_ID,
            task_signature=task_signature,
            staleness_context=staleness_context,
            limit=limit,
        )

    def _filter_stale(
        self,
        summaries: list[ActionSummary],
        staleness_context: StalenessContext | None,
    ) -> list[ActionSummary]:
        if staleness_context is None:
            return [s for s in summaries if s.validity.status not in _STALE_STATUSES]
        result: list[ActionSummary] = []
        for summary in summaries:
            updated = self._guard.apply(summary, staleness_context)
            if updated.validity.status not in _STALE_STATUSES:
                result.append(updated)
        return result


def merge_dedup_summaries(
    primary: list[ActionSummary],
    secondary: list[ActionSummary],
) -> list[ActionSummary]:
    """Merge summaries by summary_id while preserving primary precedence."""
    merged = list(primary)
    seen = {summary.summary_id for summary in merged}
    for summary in secondary:
        if summary.summary_id in seen:
            continue
        merged.append(summary)
        seen.add(summary.summary_id)
    return merged


__all__ = ["COMMON_REPO_ID", "SummaryRetriever", "merge_dedup_summaries"]
