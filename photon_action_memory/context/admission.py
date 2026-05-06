"""Context Admission Controller for ContextPack generation."""

from __future__ import annotations

import hashlib

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionSummary,
    ContextAdmissionDecision,
)
from photon_action_memory.context.budget import TokenBudgetTracker
from photon_action_memory.context.render import estimate_tokens, render_summary

_STALE_STATUSES: frozenset[str] = frozenset({"stale", "contradicted"})


def _decision_id(item_id: str) -> str:
    digest = hashlib.sha256(item_id.encode()).hexdigest()[:12]
    return f"dec-{digest}"


class ContextAdmissionController:
    """Evaluate ActionSummary candidates for admission into a ContextPack.

    Admission rules (in order):
    1. Staleness: omit if validity.status is stale or contradicted.
    2. Empty content: omit if no facts, hypotheses, failed_attempts, or avoid.
    3. Deduplication: omit if rendered text already seen.
    4. Token budget: omit if adding would exceed max_memory_tokens.
    """

    def __init__(self, tracker: TokenBudgetTracker) -> None:
        self._tracker = tracker
        self._seen: set[str] = set()

    def evaluate(self, summary: ActionSummary) -> tuple[str, str | None]:
        """Return (decision, reason) for *summary*."""
        if summary.validity.status in _STALE_STATUSES:
            base_reason = f"summary is {summary.validity.status}"
            if summary.validity.reason:
                return "omit", f"{base_reason}: {summary.validity.reason}"
            return "omit", base_reason

        has_content = bool(
            summary.facts or summary.hypotheses or summary.failed_attempts or summary.avoid
        )
        if not has_content:
            return "omit", "no admissible content"

        text = render_summary(summary)
        normalized = text.strip().lower()
        if normalized in self._seen:
            return "omit", "duplicate content"

        tokens = estimate_tokens(text)
        if not self._tracker.fits(tokens):
            return "omit", "token budget exceeded"

        self._seen.add(normalized)
        self._tracker.consume(tokens)
        return "admit", None

    def make_decision(
        self,
        summary: ActionSummary,
        decision: str,
        reason: str | None,
    ) -> ContextAdmissionDecision:
        est_tokens: int | None = None
        if decision == "admit":
            est_tokens = estimate_tokens(render_summary(summary))
        return ContextAdmissionDecision(
            schema_version=DEFAULT_SCHEMA_VERSION_V2,
            decision_id=_decision_id(summary.summary_id),
            item_id=summary.summary_id,
            item_kind="action_summary",
            decision=decision,
            reason=reason,
            estimated_tokens=est_tokens,
        )


__all__ = ["ContextAdmissionController"]
