"""Answer-leak detection for ActionSummary seeds.

Pure functions only — no I/O, no LLM call. Used by the `/v1/summary/upsert`
quality gate to flag seeds whose prompt-visible text pre-spoils the answer
of the task they will later be retrieved for.

The detector is intentionally conservative: every pattern in
``ANSWER_LEAK_PATTERNS`` must fire on a real "answer leak" example
(Anvil S1-02 family) without firing on legitimate context text such as
``"summarize.py reads JSON files"``.

The module exposes two layers:

- :func:`detect_answer_leak` — regex scan over a single string. Returns a
  list of :class:`LeakMatch` records (one per pattern hit).
- :func:`evaluate_summary_quality` — walks the prompt-visible fields of an
  :class:`ActionSummary` and returns an aggregated :class:`QualityReport`.

Callers decide the policy (strict / warn / observe). The pure function
itself only reports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from photon_action_memory.api.schema_v2 import ActionSummary

QualityCheckStatusValue = Literal["unchecked", "clean", "warned", "rejected"]


_COMPILE_FLAGS = re.IGNORECASE | re.UNICODE


# Regex SSOT. Each entry is (name, raw_pattern). Order is preserved in
# the report so callers can rely on the first match for primary triage.
#
# Patterns are deliberately tight: each one was validated against the
# S1-02 fixture family (positive) and the AL-02 false-positive case
# (``summarize.py reads JSON files``).
_ANSWER_LEAK_RAW: tuple[tuple[str, str], ...] = (
    # 1. Inline JSON object literal embedded in prompt-visible text. We
    #    require at least one quoted key followed by a value separator so
    #    bare ``{x}`` placeholders don't trip the check.
    (
        "output_literal_json",
        r"\{[^{}]*\"[A-Za-z_][\w-]*\"\s*:\s*[^{}]+\}",
    ),
    # 2. Three or more comma-separated identifiers prefaced by
    #    "with/are keys/fields/columns" — the classic "answer schema
    #    enumeration" leak from S1-02.
    (
        "output_key_enumeration",
        r"\b(?:with\s+)?(?:keys?|fields?|columns?|properties)\s*"
        r"(?:are|:|of|named|=)?\s*"
        r"[`'\"]?[A-Za-z_][\w-]*[`'\"]?"
        r"(?:\s*,\s*(?:and\s+)?[`'\"]?[A-Za-z_][\w-]*[`'\"]?){2,}",
    ),
    # 3. Declarative "X prints / outputs / returns / shows a JSON object".
    #    Catches "summarize.py prints a JSON object …" while leaving
    #    "summarize.py reads JSON files" untouched (different verbs).
    (
        "direct_print_answer",
        r"\b(?:prints?|outputs?|returns?|shows?|emits?|writes?)\s+"
        r"(?:a|an|the)?\s*json\s+(?:object|payload|response|with)\b",
    ),
    # 4. Stdout forecast: "stdout will/contains/shows/is …".
    (
        "stdout_forecast",
        r"\bstdout\s+(?:will|contains?|shows?|is|are|prints?|outputs?|returns?)\b",
    ),
    # 5. Direct answer assertion in natural language.
    (
        "answer_assertion",
        r"\bthe\s+(?:answer|result|output|response|expected\s+(?:output|value))\s+"
        r"(?:is|will\s+be|should\s+be|equals?|=)\b",
    ),
    # 6. Numeric equality / "equals N" pinned to a leading identifier so
    #    "limit=50" in comments isn't tripped, but
    #    "total equals 30" or "total = 30" is.
    (
        "numeric_answer_equality",
        r"\b[A-Za-z_]\w{2,}\s*(?:=|equals?|is)\s*-?\d+(?:\.\d+)?\b",
    ),
)


ANSWER_LEAK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, _COMPILE_FLAGS)) for name, pattern in _ANSWER_LEAK_RAW
)


@dataclass(frozen=True)
class LeakMatch:
    """One regex hit on a single text value."""

    pattern: str
    start: int
    end: int
    snippet: str


@dataclass(frozen=True)
class QualityReport:
    """Aggregate quality result for one :class:`ActionSummary`.

    ``status`` is the worst across every prompt-visible field. The pure
    function never emits ``"rejected"`` — that is the strict-mode
    decision made by the caller. We expose the literal so the schema
    type alias can be shared.
    """

    status: QualityCheckStatusValue
    warnings: tuple[str, ...] = ()
    matches: tuple[tuple[str, LeakMatch], ...] = field(default_factory=tuple)


def detect_answer_leak(text: str) -> list[LeakMatch]:
    """Scan ``text`` for known answer-leak patterns.

    Returns at most one match per pattern (the first hit) so the report
    surfaces *which kind* of leak was found without flooding callers
    with overlapping matches from the same pattern.
    """
    if not text:
        return []
    out: list[LeakMatch] = []
    for name, compiled in ANSWER_LEAK_PATTERNS:
        match = compiled.search(text)
        if match is None:
            continue
        out.append(
            LeakMatch(
                pattern=name,
                start=match.start(),
                end=match.end(),
                snippet=match.group(0),
            )
        )
    return out


def evaluate_summary_quality(summary: ActionSummary) -> QualityReport:
    """Aggregate answer-leak detection across an ``ActionSummary``.

    Walks the prompt-visible text fields (``facts[*].text``,
    ``next_hints[*].reason``, ``next_hints[*].target``, and
    ``avoid[*].reason``). ``actions_done`` and ``failed_attempts``
    describe past behaviour, not the current answer, so they are out of
    scope for this gate.
    """
    warnings: list[str] = []
    field_matches: list[tuple[str, LeakMatch]] = []

    for index, fact in enumerate(summary.facts):
        for match in detect_answer_leak(fact.text):
            path = f"facts[{index}].text"
            warnings.append(_format_warning(path, match))
            field_matches.append((path, match))

    for index, hint in enumerate(summary.next_hints):
        if hint.reason:
            for match in detect_answer_leak(hint.reason):
                path = f"next_hints[{index}].reason"
                warnings.append(_format_warning(path, match))
                field_matches.append((path, match))
        if hint.target:
            for match in detect_answer_leak(hint.target):
                path = f"next_hints[{index}].target"
                warnings.append(_format_warning(path, match))
                field_matches.append((path, match))

    for index, avoid in enumerate(summary.avoid):
        if avoid.reason:
            for match in detect_answer_leak(avoid.reason):
                path = f"avoid[{index}].reason"
                warnings.append(_format_warning(path, match))
                field_matches.append((path, match))

    status: QualityCheckStatusValue = "warned" if warnings else "clean"
    return QualityReport(
        status=status,
        warnings=tuple(warnings),
        matches=tuple(field_matches),
    )


def _format_warning(path: str, match: LeakMatch) -> str:
    snippet = match.snippet.strip()
    if len(snippet) > 80:
        snippet = snippet[:77] + "..."
    return f"{path}: {match.pattern}: '{snippet}'"


__all__ = [
    "ANSWER_LEAK_PATTERNS",
    "LeakMatch",
    "QualityCheckStatusValue",
    "QualityReport",
    "detect_answer_leak",
    "evaluate_summary_quality",
]
