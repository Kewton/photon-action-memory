"""Action Summary Builder, Canonicalizer, and State Updater for v0.2."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionChunk,
    ActionDone,
    ActionSummary,
    AvoidGuidance,
    Fact,
    FailedAttempt,
    Hypothesis,
    NextHint,
    TokenCost,
    Validity,
)

_CHARS_PER_TOKEN: int = 4
_HEURISTIC_RAW_TOKENS_PER_EVENT: int = 200


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _deterministic_summary_id(*parts: str) -> str:
    key = "\n".join(parts)
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f"sum-{digest}"


class _HasText(Protocol):
    """Structural type for items that can be deduplicated by `.text`."""

    @property
    def text(self) -> str: ...


class ActionSummaryBuilder:
    """Convert a single ActionChunk into an ActionSummary using deterministic heuristics.

    No external model is required; all claims are grounded in chunk.event_ids.
    Rules (deterministic fallback from 04_architecture.md section 8):
    - outcome=useful + event_ids present -> Fact
    - outcome=partial                    -> Hypothesis (open, confidence 0.5)
    - outcome=failed                     -> FailedAttempt (never Fact)
    - outcome=irrelevant                 -> AvoidGuidance
    """

    def build(
        self,
        chunk: ActionChunk,
        *,
        summary_id: str | None = None,
    ) -> ActionSummary:
        """Return an ActionSummary derived from *chunk*."""
        sid = summary_id or _deterministic_summary_id(chunk.chunk_id)
        evidence_ids = list(chunk.event_ids)
        outcome = str(chunk.outcome)

        return ActionSummary(
            schema_version=DEFAULT_SCHEMA_VERSION_V2,
            summary_id=sid,
            session_id=chunk.session_id,
            repo_id=chunk.repo_id,
            commit=chunk.commit,
            summary_level="chunk",
            source_chunk_ids=[chunk.chunk_id],
            actions_done=self._actions_done(chunk, evidence_ids, outcome),
            facts=self._facts(chunk, evidence_ids, outcome),
            hypotheses=self._hypotheses(chunk, evidence_ids, outcome),
            failed_attempts=self._failed_attempts(chunk, evidence_ids, outcome),
            avoid=self._avoid(chunk, evidence_ids, outcome),
            next_hints=self._next_hints(chunk, outcome),
            token_cost=self._token_cost(chunk),
            validity=Validity(status="valid"),
        )

    # ------------------------------------------------------------------
    # Internal builders - each returns a typed list.
    # ------------------------------------------------------------------

    def _actions_done(
        self,
        chunk: ActionChunk,
        evidence_ids: list[str],
        outcome: str,
    ) -> list[ActionDone]:
        return [
            ActionDone(
                kind=str(chunk.kind),
                outcome=chunk.summary,
                status=outcome,
                evidence_ids=evidence_ids,
            )
        ]

    def _facts(
        self,
        chunk: ActionChunk,
        evidence_ids: list[str],
        outcome: str,
    ) -> list[Fact]:
        # Facts require evidence_ids and a definitively successful outcome.
        if outcome != "useful" or not evidence_ids:
            return []
        return [Fact(text=chunk.summary, evidence_ids=evidence_ids, confidence=0.9)]

    def _hypotheses(
        self,
        chunk: ActionChunk,
        evidence_ids: list[str],
        outcome: str,
    ) -> list[Hypothesis]:
        # Partial outcomes produce open hypotheses, separated from facts.
        if outcome != "partial":
            return []
        return [
            Hypothesis(
                text=chunk.summary,
                evidence_ids=evidence_ids,
                confidence=0.5,
                status="open",
            )
        ]

    def _failed_attempts(
        self,
        chunk: ActionChunk,
        evidence_ids: list[str],
        outcome: str,
    ) -> list[FailedAttempt]:
        # Failed actions tracked separately to prevent pointless retries.
        if outcome != "failed":
            return []
        return [
            FailedAttempt(
                action=f"{chunk.kind}: {chunk.summary}",
                outcome=chunk.summary,
                evidence_ids=evidence_ids,
                retry_policy="avoid_until_files_changed",
            )
        ]

    def _avoid(
        self,
        chunk: ActionChunk,
        evidence_ids: list[str],
        outcome: str,
    ) -> list[AvoidGuidance]:
        if outcome != "irrelevant":
            return []
        return [
            AvoidGuidance(
                action=f"{chunk.kind}: {chunk.summary}",
                reason="action produced no useful result",
                evidence_ids=evidence_ids,
            )
        ]

    def _next_hints(self, chunk: ActionChunk, outcome: str) -> list[NextHint]:
        if outcome == "failed":
            return [
                NextHint(
                    kind="inspect",
                    reason="investigate failure before retrying",
                    confidence=0.6,
                )
            ]
        if outcome in ("useful", "partial") and chunk.kind == "repo_search":
            return [NextHint(kind="read", reason="inspect files found by search", confidence=0.7)]
        return []

    def _token_cost(self, chunk: ActionChunk) -> TokenCost:
        summary_tokens = _estimate_tokens(chunk.summary)
        raw_tokens = max(
            summary_tokens,
            len(chunk.event_ids) * _HEURISTIC_RAW_TOKENS_PER_EVENT,
        )
        return TokenCost(
            estimated_summary_tokens=summary_tokens,
            estimated_raw_tokens=raw_tokens,
            tokens_saved_vs_raw=raw_tokens - summary_tokens,
        )


@dataclass
class CanonicalizeResult:
    """Outcome of a canonicalize pass."""

    summary: ActionSummary
    removed_ungrounded_facts: int = 0
    warnings: list[str] = field(default_factory=list)


class SummaryCanonicalizer:
    """Validate and normalize an ActionSummary to enforce evidence-grounding rules.

    Key invariant: every prompt-visible fact must carry at least one evidence_id.
    Facts without evidence_ids are removed and the validity is downgraded to
    ``partial`` so callers can detect the degradation.
    """

    def canonicalize(self, summary: ActionSummary) -> CanonicalizeResult:
        """Return a normalized summary and a report of any items removed."""
        grounded: list[Fact] = []
        removed = 0
        warnings: list[str] = []

        for fact in summary.facts:
            if fact.evidence_ids:
                grounded.append(fact)
            else:
                removed += 1
                warnings.append(f"removed ungrounded fact: {fact.text[:60]!r}")

        validity = summary.validity
        if removed > 0 and validity.status == "valid":
            validity = Validity(
                status="partial",
                reason=f"removed {removed} ungrounded fact(s)",
            )

        updated = summary.model_copy(update={"facts": grounded, "validity": validity})
        return CanonicalizeResult(
            summary=updated,
            removed_ungrounded_facts=removed,
            warnings=warnings,
        )


class SummaryStateUpdater:
    """Incrementally update an existing ActionSummary with a new ActionChunk.

    Implements the recursive state update from 04_architecture.md section 4:
        S_t = update(S_{t-1}, ActionChunk_t)

    The updater builds a chunk-level summary, canonicalizes it, then merges it
    into the previous state.  Deduplication is by text/action identity so that
    repeated observations do not inflate the summary.
    """

    def __init__(self) -> None:
        self._builder = ActionSummaryBuilder()
        self._canonicalizer = SummaryCanonicalizer()

    def update(
        self,
        previous: ActionSummary,
        chunk: ActionChunk,
        *,
        summary_id: str | None = None,
    ) -> ActionSummary:
        """Merge *chunk* into *previous* and return the updated state."""
        chunk_summary = self._builder.build(chunk)
        result = self._canonicalizer.canonicalize(chunk_summary)
        new = result.summary

        sid = summary_id or _deterministic_summary_id(previous.summary_id, chunk.chunk_id)

        return ActionSummary(
            schema_version=DEFAULT_SCHEMA_VERSION_V2,
            summary_id=sid,
            session_id=previous.session_id or chunk.session_id,
            repo_id=previous.repo_id or chunk.repo_id,
            commit=chunk.commit or previous.commit,
            summary_level=previous.summary_level,
            source_chunk_ids=[*previous.source_chunk_ids, chunk.chunk_id],
            actions_done=[*previous.actions_done, *new.actions_done],
            facts=_merge_by_text(previous.facts, new.facts),
            hypotheses=_merge_by_text(previous.hypotheses, new.hypotheses),
            failed_attempts=_merge_failed(previous.failed_attempts, new.failed_attempts),
            avoid=_merge_avoid(previous.avoid, new.avoid),
            next_hints=new.next_hints,  # newer chunk's hints are more relevant
            token_cost=_add_token_costs(previous.token_cost, new.token_cost),
            validity=Validity(status="valid"),
        )


# ---------------------------------------------------------------------------
# Merge helpers - module-private
# ---------------------------------------------------------------------------


def _merge_by_text[T: _HasText](prev: list[T], new: list[T]) -> list[T]:
    seen: set[str] = {item.text for item in prev}
    return [*prev, *(item for item in new if item.text not in seen)]


def _merge_failed(
    prev: list[FailedAttempt],
    new: list[FailedAttempt],
) -> list[FailedAttempt]:
    seen: set[str] = {f.action for f in prev}
    return [*prev, *(f for f in new if f.action not in seen)]


def _merge_avoid(
    prev: list[AvoidGuidance],
    new: list[AvoidGuidance],
) -> list[AvoidGuidance]:
    seen: set[str] = {a.action for a in prev}
    return [*prev, *(a for a in new if a.action not in seen)]


def _add_token_costs(prev: TokenCost | None, new: TokenCost | None) -> TokenCost | None:
    if prev is None:
        return new
    if new is None:
        return prev
    summary = prev.estimated_summary_tokens + new.estimated_summary_tokens
    raw = prev.estimated_raw_tokens + new.estimated_raw_tokens
    return TokenCost(
        estimated_summary_tokens=summary,
        estimated_raw_tokens=raw,
        tokens_saved_vs_raw=raw - summary,
    )


__all__ = [
    "ActionSummaryBuilder",
    "CanonicalizeResult",
    "SummaryCanonicalizer",
    "SummaryStateUpdater",
]
