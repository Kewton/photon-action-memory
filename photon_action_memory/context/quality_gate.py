"""Task-aware quality gate for prompt-visible ActionSummary admission."""

from __future__ import annotations

import re
from dataclasses import dataclass

from photon_action_memory.api.schema_v2 import ActionSummary

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "with",
    }
)
_DIRECT_NEXT_ACTIONS = frozenset(
    {
        "add",
        "change",
        "create",
        "implement",
        "insert",
        "modify",
        "replace",
        "set",
        "update",
        "use",
        "write",
    }
)
_META_MARKERS = (
    "anvil.md",
    "custom_check.py",
    "do not use pytest",
    "preferred verifier",
    "use python3 custom_check.py",
)
_VERIFY_MARKERS = (
    "before final",
    "final answer",
    "run verification",
    "run verifier",
    "verify before",
)


@dataclass(frozen=True)
class SummaryQualityGateResult:
    """Result of task-aware quality evaluation for one summary."""

    decision: str
    reason: str | None = None
    risk: str | None = None
    warnings: tuple[str, ...] = ()
    task_overlap: float = 0.0
    novel_ratio: float = 1.0


def evaluate_summary_quality(
    summary: ActionSummary, task_text: str | None
) -> SummaryQualityGateResult:
    """Reject summaries that mostly repeat the current task and shortcut exploration."""
    task_tokens = _tokens(task_text or "")
    if not task_tokens:
        return SummaryQualityGateResult(decision="allow")

    summary_text = _summary_prompt_text(summary)
    summary_tokens = _tokens(summary_text)
    if not summary_tokens:
        return SummaryQualityGateResult(decision="allow")

    overlap = len(summary_tokens & task_tokens) / len(summary_tokens)
    novel_ratio = len(summary_tokens - task_tokens) / len(summary_tokens)
    meta_info = _has_meta_information(summary_text)
    verification_guidance = _has_verification_guidance(summary)
    premature_risk = _has_premature_termination_risk(summary, task_tokens)

    warnings: list[str] = []
    if premature_risk:
        warnings.append(
            f"{summary.summary_id}: premature_termination_risk: "
            "direct next_hint overlaps current task"
        )

    if meta_info or verification_guidance:
        return SummaryQualityGateResult(
            decision="allow",
            warnings=tuple(warnings),
            task_overlap=overlap,
            novel_ratio=novel_ratio,
        )

    low_value_overlap = overlap >= 0.50 and novel_ratio <= 0.50
    shortcut_overlap = premature_risk and overlap >= 0.30
    if low_value_overlap or shortcut_overlap:
        reason = (
            "summary quality gate rejected: low_value task overlap "
            f"(overlap={overlap:.2f}, novel={novel_ratio:.2f})"
        )
        if premature_risk:
            reason += "; premature_termination_risk"
        return SummaryQualityGateResult(
            decision="reject",
            reason=reason,
            risk="medium" if premature_risk else "low",
            warnings=tuple(warnings),
            task_overlap=overlap,
            novel_ratio=novel_ratio,
        )

    return SummaryQualityGateResult(
        decision="allow",
        warnings=tuple(warnings),
        task_overlap=overlap,
        novel_ratio=novel_ratio,
    )


def _tokens(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(text.lower()) if token not in _STOPWORDS}


def _summary_prompt_text(summary: ActionSummary) -> str:
    parts: list[str] = []
    parts.extend(fact.text for fact in summary.facts)
    parts.extend(hyp.text for hyp in summary.hypotheses)
    parts.extend(failed.action for failed in summary.failed_attempts)
    parts.extend(failed.outcome for failed in summary.failed_attempts)
    for avoid in summary.avoid:
        parts.append(avoid.action)
        parts.append(avoid.reason)
    for hint in summary.next_hints:
        parts.append(hint.kind)
        if hint.target:
            parts.append(hint.target)
        parts.append(hint.reason)
    return "\n".join(part for part in parts if part)


def _has_meta_information(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _META_MARKERS)


def _has_verification_guidance(summary: ActionSummary) -> bool:
    for hint in summary.next_hints:
        text = f"{hint.kind} {hint.reason}".lower()
        if hint.kind.lower() in {"verify", "test"}:
            return True
        if any(marker in text for marker in _VERIFY_MARKERS):
            return True
    return False


def _has_premature_termination_risk(summary: ActionSummary, task_tokens: set[str]) -> bool:
    for hint in summary.next_hints:
        if hint.kind.lower() in {"verify", "test", "inspect", "read"}:
            continue
        hint_tokens = _tokens(f"{hint.kind} {hint.target or ''} {hint.reason}")
        if not hint_tokens:
            continue
        direct_action = bool(hint_tokens & _DIRECT_NEXT_ACTIONS)
        overlap = len(hint_tokens & task_tokens) / len(hint_tokens)
        if direct_action and overlap >= 0.35:
            return True
    return False


__all__ = ["SummaryQualityGateResult", "evaluate_summary_quality"]
