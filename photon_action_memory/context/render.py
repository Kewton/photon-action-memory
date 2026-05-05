"""Render ActionSummary items to prompt-visible text."""

from __future__ import annotations

from photon_action_memory.api.schema_v2 import ActionSummary

_CHARS_PER_TOKEN: int = 4


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def render_summary(summary: ActionSummary) -> str:
    """Render an ActionSummary to compact prompt-visible text."""
    parts: list[str] = []
    for fact in summary.facts:
        parts.append(f"FACT: {fact.text}")
    for hyp in summary.hypotheses:
        parts.append(f"HYPOTHESIS: {hyp.text}")
    for fa in summary.failed_attempts:
        parts.append(f"FAILED: {fa.action}")
    for av in summary.avoid:
        parts.append(f"AVOID: {av.action} - {av.reason}")
    for nh in summary.next_hints:
        parts.append(f"HINT: {nh.kind} - {nh.reason}")
    return "\n".join(parts)


__all__ = ["estimate_tokens", "render_summary"]
