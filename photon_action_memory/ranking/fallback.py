"""No-model fallback ranking placeholder."""

from __future__ import annotations


def rank_candidates(candidates: list[str], *, limit: int) -> list[str]:
    """Return deterministic top-k candidates."""
    return candidates[: max(limit, 0)]
