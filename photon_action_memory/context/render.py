"""Render ActionSummary items to prompt-visible text."""

from __future__ import annotations

from collections.abc import Iterable

from photon_action_memory.api.schema_v2 import ActionSummary
from photon_action_memory.memory.sanitizer import sanitize_text

_CHARS_PER_TOKEN: int = 4


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def render_summary(
    summary: ActionSummary,
    *,
    exclude_next_hint_indices: Iterable[int] | None = None,
) -> str:
    """Render an ActionSummary to compact prompt-visible text."""
    excluded_hints = set(exclude_next_hint_indices or ())
    parts: list[str] = []
    for fact in summary.facts:
        parts.append(f"FACT: {fact.text}")
    for hyp in summary.hypotheses:
        parts.append(f"HYPOTHESIS: {hyp.text}")
    for fa in summary.failed_attempts:
        parts.append(f"FAILED: {fa.action}")
    for av in summary.avoid:
        parts.append(f"AVOID: {av.action} - {av.reason}")
    for index, nh in enumerate(summary.next_hints):
        if index in excluded_hints:
            continue
        parts.append(f"HINT: {nh.kind} - {nh.reason}")
    return sanitize_text("\n".join(parts))


__all__ = ["estimate_tokens", "render_summary"]
