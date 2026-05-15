"""Task-aware quality gate for prompt-visible ActionSummary admission."""

from __future__ import annotations

import os
from dataclasses import dataclass

from photon_action_memory.api.schema_v2 import ActionSummary
from photon_action_memory.context.overlap_detector import (
    OverlapDetectorMode,
    compute_overlap,
    tokenize,
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
_PREMATURE_THRESHOLD_ENV = "PHOTON_PREMATURE_OVERLAP_THRESHOLD"
_DEFAULT_PREMATURE_THRESHOLD = 0.15
_CONCRETE_CODE_CHANGE_MARKERS = (
    "return ",
    "change return",
    " to return ",
    "->",
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
    suppressed_next_hint_indices: tuple[int, ...] = ()


def evaluate_summary_quality(
    summary: ActionSummary,
    task_text: str | None,
    *,
    mode: OverlapDetectorMode | None = None,
) -> SummaryQualityGateResult:
    """Reject summaries that mostly repeat the current task and shortcut exploration.

    ``mode`` selects the overlap detector (``ascii``/``multilingual``/
    ``embedding``/``hybrid``). When ``None`` the configured default is used so
    cross-lingual task↔seed combinations are detected without the caller
    having to opt in.
    """
    task_text_norm = task_text or ""
    task_tokens = tokenize(task_text_norm, mode=mode)
    if not task_tokens:
        return SummaryQualityGateResult(decision="allow")

    summary_text = _summary_prompt_text(summary)
    summary_tokens = tokenize(summary_text, mode=mode)
    if not summary_tokens:
        return SummaryQualityGateResult(decision="allow")

    overlap_result = compute_overlap(summary_text, task_text_norm, mode=mode)
    overlap = overlap_result.overlap
    novel_ratio = overlap_result.novel
    meta_info = _has_meta_information(summary_text)
    verification_guidance = _has_verification_guidance(summary)
    suppressed_hint_indices = _premature_termination_next_hint_indices(
        summary,
        task_tokens,
        mode=mode,
    )
    premature_risk = bool(suppressed_hint_indices)

    warnings: list[str] = []
    if premature_risk and not meta_info:
        warnings.append(
            f"{summary.summary_id}: premature_termination_risk: "
            "direct next_hint overlaps current task"
        )

    if meta_info or (verification_guidance and not premature_risk):
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
            suppressed_next_hint_indices=suppressed_hint_indices,
        )

    return SummaryQualityGateResult(
        decision="allow",
        warnings=tuple(warnings),
        task_overlap=overlap,
        novel_ratio=novel_ratio,
        suppressed_next_hint_indices=suppressed_hint_indices,
    )


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


def _premature_termination_next_hint_indices(
    summary: ActionSummary,
    task_tokens: set[str],
    *,
    mode: OverlapDetectorMode | None = None,
) -> tuple[int, ...]:
    risky_indices: list[int] = []
    for index, hint in enumerate(summary.next_hints):
        if hint.kind.lower() in {"verify", "test", "inspect", "read"}:
            continue
        hint_text = f"{hint.kind} {hint.target or ''} {hint.reason}"
        if _has_concrete_code_change(hint_text):
            continue
        hint_tokens = tokenize(hint_text, mode=mode)
        if not hint_tokens:
            continue
        direct_action = bool(hint_tokens & _DIRECT_NEXT_ACTIONS)
        overlap = len(hint_tokens & task_tokens) / len(hint_tokens)
        if direct_action and overlap >= premature_overlap_threshold():
            risky_indices.append(index)
    return tuple(risky_indices)


def premature_overlap_threshold() -> float:
    """Return the direct next-hint overlap threshold for premature risk.

    The default is intentionally lower than the original 0.35 so realistic
    Anvil task phrasing can still trip the warning. Invalid environment values
    fail closed to the default instead of disabling the gate.
    """
    raw = (os.environ.get(_PREMATURE_THRESHOLD_ENV) or "").strip()
    if not raw:
        return _DEFAULT_PREMATURE_THRESHOLD
    try:
        threshold = float(raw)
    except ValueError:
        return _DEFAULT_PREMATURE_THRESHOLD
    if threshold < 0.0:
        return 0.0
    if threshold > 1.0:
        return 1.0
    return threshold


def _has_concrete_code_change(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _CONCRETE_CODE_CHANGE_MARKERS)


__all__ = [
    "SummaryQualityGateResult",
    "evaluate_summary_quality",
    "premature_overlap_threshold",
]
