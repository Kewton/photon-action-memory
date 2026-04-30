"""Deterministic candidate extraction placeholder."""

from __future__ import annotations


def extract_candidates(items: list[str]) -> list[str]:
    """Deduplicate candidate strings while preserving input order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
