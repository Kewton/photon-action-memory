"""Syntax-based contradiction detection between ActionSummary seeds.

Pure functions only — no I/O, no LLM call. The detector compares
summaries that share ``repo_id + task_signature`` and emits a
:class:`ContradictionPair` for each rule that fires.

Rules (all token comparisons use Jaccard over the multilingual
tokenizer the quality gate already uses):

1. ``avoid_vs_action``           — ``a.avoid[*].action`` overlaps a
   ``b.actions_done`` command/target or a ``b.next_hints`` target.
2. ``avoid_polarity_conflict``   — both summaries warn about the same
   action but with opposite polarity in the reason.
3. ``fact_negation``             — overlapping facts with one carrying
   a negation marker the other does not.
4. ``next_hint_conflict``        — opposite verbs (``add`` vs
   ``remove`` etc.) on overlapping next-hint targets.
5. ``failed_attempt_vs_next_hint`` — ``a.failed_attempts`` action
   overlaps ``b.next_hints`` target (suggesting a known-failing
   action).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from photon_action_memory.api.schema_v2 import ActionSummary
from photon_action_memory.context.overlap_detector import tokenize

_AVOID_VS_ACTION_THRESHOLD = 0.5
_AVOID_VS_AVOID_THRESHOLD = 0.5
_FACT_NEGATION_THRESHOLD = 0.5
_NEXT_HINT_THRESHOLD = 0.5
_FAILED_VS_HINT_THRESHOLD = 0.6

# Negation markers shared by avoid-reason and fact-text checks. Order is not
# meaningful, but ``do not`` must come before ``not `` so the longer form
# matches for de-duplicating "do not" inside polarity reporting.
_NEGATION_MARKERS: tuple[str, ...] = (
    "do not",
    "don't",
    "does not",
    "doesn't",
    "must not",
    "should not",
    "shouldn't",
    "cannot",
    "can't",
    "never",
    "no longer",
    "not ",
    " not.",
    "ない",
    "しない",
    "禁止",
    "不可",
)
# Verb pairs that cancel each other in next_hints.
_OPPOSITE_VERB_PAIRS: tuple[tuple[str, str], ...] = (
    ("add", "remove"),
    ("add", "delete"),
    ("create", "delete"),
    ("enable", "disable"),
    ("use", "avoid"),
    ("keep", "remove"),
    ("keep", "delete"),
    ("install", "uninstall"),
    ("start", "stop"),
    ("show", "hide"),
)


@dataclass(frozen=True)
class ContradictionPair:
    """A pair of summaries identified as contradictory."""

    summary_a_id: str
    summary_b_id: str
    kind: str
    evidence: str

    def to_dict(self) -> dict[str, str]:
        return {
            "summary_a_id": self.summary_a_id,
            "summary_b_id": self.summary_b_id,
            "kind": self.kind,
            "evidence": self.evidence,
        }


def detect_contradictions(
    summaries: Iterable[ActionSummary],
) -> list[ContradictionPair]:
    """Return contradictions among ``summaries`` sharing repo+task scope.

    Summaries are grouped by ``(repo_id, task_signature)``; pairs are
    only compared inside the same group so the result remains O(n²) per
    scope rather than O(N²) globally. Group membership for ``None``
    values is exact: ``repo_id=None`` is its own bucket and never
    matches a populated ``repo_id``.
    """
    grouped: dict[tuple[str | None, str | None], list[ActionSummary]] = {}
    for summary in summaries:
        key = (summary.repo_id, summary.task_signature)
        grouped.setdefault(key, []).append(summary)

    pairs: list[ContradictionPair] = []
    for group in grouped.values():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            a = group[i]
            for j in range(i + 1, len(group)):
                b = group[j]
                pairs.extend(_compare_pair(a, b))
    return pairs


def _compare_pair(a: ActionSummary, b: ActionSummary) -> list[ContradictionPair]:
    found: list[ContradictionPair] = []
    found.extend(_check_avoid_vs_action(a, b))
    found.extend(_check_avoid_vs_action(b, a))
    found.extend(_check_avoid_polarity(a, b))
    found.extend(_check_fact_negation(a, b))
    found.extend(_check_next_hint_conflict(a, b))
    found.extend(_check_failed_vs_next_hint(a, b))
    found.extend(_check_failed_vs_next_hint(b, a))
    return _dedup(found)


def _check_avoid_vs_action(
    avoider: ActionSummary,
    actor: ActionSummary,
) -> list[ContradictionPair]:
    """Avoid guidance on one side that contradicts an action on the other."""
    out: list[ContradictionPair] = []
    if not avoider.avoid:
        return out
    actor_targets: list[tuple[str, str]] = []
    for done in actor.actions_done:
        for value in (done.command, done.target):
            if value:
                actor_targets.append(("actions_done", value))
    for hint in actor.next_hints:
        if hint.target:
            actor_targets.append(("next_hints", hint.target))
    if not actor_targets:
        return out
    for guidance in avoider.avoid:
        guidance_text = guidance.action
        guidance_tokens = tokenize(guidance_text)
        if not guidance_tokens:
            continue
        for source, target_text in actor_targets:
            target_tokens = tokenize(target_text)
            if _jaccard(guidance_tokens, target_tokens) < _AVOID_VS_ACTION_THRESHOLD:
                continue
            out.append(
                ContradictionPair(
                    summary_a_id=avoider.summary_id,
                    summary_b_id=actor.summary_id,
                    kind="avoid_vs_action",
                    evidence=(
                        f"avoid '{guidance_text}' contradicts {source} '{target_text}'"
                    ),
                )
            )
    return out


def _check_avoid_polarity(
    a: ActionSummary,
    b: ActionSummary,
) -> list[ContradictionPair]:
    """Both seeds warn about the same action but with opposite stance.

    Polarity is detected by negation markers in the ``reason`` text:
    when one reason contains a negation marker and the other does not,
    they disagree on whether the action should be taken.
    """
    out: list[ContradictionPair] = []
    if not a.avoid or not b.avoid:
        return out
    for guidance_a in a.avoid:
        tokens_a = tokenize(guidance_a.action)
        if not tokens_a:
            continue
        for guidance_b in b.avoid:
            tokens_b = tokenize(guidance_b.action)
            if not tokens_b:
                continue
            if _jaccard(tokens_a, tokens_b) < _AVOID_VS_AVOID_THRESHOLD:
                continue
            neg_a = _has_negation(guidance_a.reason)
            neg_b = _has_negation(guidance_b.reason)
            if neg_a == neg_b:
                continue
            out.append(
                ContradictionPair(
                    summary_a_id=a.summary_id,
                    summary_b_id=b.summary_id,
                    kind="avoid_polarity_conflict",
                    evidence=(
                        f"avoid '{guidance_a.action}' "
                        f"reason '{guidance_a.reason}' vs '{guidance_b.reason}'"
                    ),
                )
            )
    return out


def _check_fact_negation(
    a: ActionSummary,
    b: ActionSummary,
) -> list[ContradictionPair]:
    out: list[ContradictionPair] = []
    if not a.facts or not b.facts:
        return out
    for fact_a in a.facts:
        tokens_a = tokenize(fact_a.text)
        if not tokens_a:
            continue
        neg_a = _has_negation(fact_a.text)
        for fact_b in b.facts:
            tokens_b = tokenize(fact_b.text)
            if not tokens_b:
                continue
            if _jaccard(tokens_a, tokens_b) < _FACT_NEGATION_THRESHOLD:
                continue
            neg_b = _has_negation(fact_b.text)
            if neg_a == neg_b:
                continue
            out.append(_fact_pair(a, b, fact_a.text, fact_b.text))
    return out


def _fact_pair(
    a: ActionSummary,
    b: ActionSummary,
    text_a: str,
    text_b: str,
) -> ContradictionPair:
    return ContradictionPair(
        summary_a_id=a.summary_id,
        summary_b_id=b.summary_id,
        kind="fact_negation",
        evidence=f"fact '{text_a}' vs '{text_b}'",
    )


def _check_next_hint_conflict(
    a: ActionSummary,
    b: ActionSummary,
) -> list[ContradictionPair]:
    out: list[ContradictionPair] = []
    if not a.next_hints or not b.next_hints:
        return out
    for hint_a in a.next_hints:
        kind_a = hint_a.kind.lower().strip()
        target_a = (hint_a.target or "").lower().strip()
        if not kind_a:
            continue
        for hint_b in b.next_hints:
            kind_b = hint_b.kind.lower().strip()
            target_b = (hint_b.target or "").lower().strip()
            if not _is_opposite_verb(kind_a, kind_b):
                continue
            if not target_a or not target_b:
                continue
            tokens_a = tokenize(target_a)
            tokens_b = tokenize(target_b)
            if not tokens_a or not tokens_b:
                continue
            if _jaccard(tokens_a, tokens_b) < _NEXT_HINT_THRESHOLD:
                continue
            out.append(
                ContradictionPair(
                    summary_a_id=a.summary_id,
                    summary_b_id=b.summary_id,
                    kind="next_hint_conflict",
                    evidence=(
                        f"next_hint '{kind_a} {target_a}' "
                        f"vs '{kind_b} {target_b}'"
                    ),
                )
            )
    return out


def _check_failed_vs_next_hint(
    a: ActionSummary,
    b: ActionSummary,
) -> list[ContradictionPair]:
    out: list[ContradictionPair] = []
    if not a.failed_attempts or not b.next_hints:
        return out
    for failed in a.failed_attempts:
        failed_tokens = tokenize(failed.action)
        if not failed_tokens:
            continue
        for hint in b.next_hints:
            target = hint.target or ""
            target_tokens = tokenize(target)
            if not target_tokens:
                continue
            if _jaccard(failed_tokens, target_tokens) < _FAILED_VS_HINT_THRESHOLD:
                continue
            out.append(
                ContradictionPair(
                    summary_a_id=a.summary_id,
                    summary_b_id=b.summary_id,
                    kind="failed_attempt_vs_next_hint",
                    evidence=(
                        f"failed attempt '{failed.action}' suggested again as "
                        f"next_hint '{hint.kind} {target}'"
                    ),
                )
            )
    return out


# ---------------------------------------------------------------------------
# helpers


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return intersection / union


def _has_negation(text: str) -> bool:
    """Return True when ``text`` contains a recognized negation marker."""
    if not text:
        return False
    lowered = text.lower()
    return any(marker in lowered for marker in _NEGATION_MARKERS)


def _is_opposite_verb(left: str, right: str) -> bool:
    if not left or not right or left == right:
        return False
    for x, y in _OPPOSITE_VERB_PAIRS:
        if (left == x and right == y) or (left == y and right == x):
            return True
    return False


def _dedup(pairs: list[ContradictionPair]) -> list[ContradictionPair]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[ContradictionPair] = []
    for pair in pairs:
        key = _normalize_key(pair)
        if key in seen:
            continue
        seen.add(key)
        out.append(pair)
    return out


def _normalize_key(pair: ContradictionPair) -> tuple[str, str, str, str]:
    a, b = sorted([pair.summary_a_id, pair.summary_b_id])
    return (a, b, pair.kind, pair.evidence)


__all__ = [
    "ContradictionPair",
    "detect_contradictions",
]
