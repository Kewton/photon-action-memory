"""Summary fidelity checker for ActionSummary validation."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from photon_action_memory.api.schema_v2 import (
    ActionSummary,
    SummaryValidationIssue,
    SummaryValidationResult,
)
from photon_action_memory.context.raw_policy import has_sensitive_content

_UNCERTAINTY_KEYWORDS: tuple[str, ...] = (
    "appears",
    "could",
    "likely",
    "maybe",
    "might",
    "perhaps",
    "possibly",
    "presumably",
    "seems",
    "suspect",
    "unclear",
    "uncertain",
    "probably",
)
_UNCERTAINTY_PATTERN: re.Pattern[str] = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in _UNCERTAINTY_KEYWORDS) + r")\b",
    re.IGNORECASE,
)
_FAILURE_OUTCOMES: frozenset[str] = frozenset({"failed", "failure", "error", "fail"})
_BLOCKING_KINDS: frozenset[str] = frozenset(
    {
        "missing_evidence_id",
        "ungrounded_fact",
        "failed_action_misclassified",
        "raw_output_in_field",
    }
)
_TEXT_FIELDS: tuple[str, ...] = ("content", "text", "message", "output", "body")
_STOP_WORDS: frozenset[str] = frozenset(
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
        "has",
        "have",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "with",
    }
)
_WORD_PATTERN: re.Pattern[str] = re.compile(r"[a-z0-9_]+")


class SummaryFidelityChecker:
    """Validates ActionSummary objects against fidelity and grounding criteria.

    Pass evidence records at construction time to enable grounding checks.
    Without records, only structural checks (missing evidence_ids, uncertainty
    language in facts) are run.
    """

    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        self._evidence_ids: set[str] = set()
        self._evidence_text_by_id: dict[str, str] = {}
        for record in records or []:
            eid = record.get("evidence_id") or record.get("event_id")
            if isinstance(eid, str) and eid:
                self._evidence_ids.add(eid)
                text = self._extract_evidence_text(record)
                if text:
                    self._evidence_text_by_id[eid] = text

    def check(self, summary: ActionSummary) -> SummaryValidationResult:
        """Run all fidelity checks on one ActionSummary."""
        issues: list[SummaryValidationIssue] = []
        self._check_facts(summary, issues)
        self._check_actions_done(summary, issues)
        self._check_raw_leakage(summary, issues)
        score = self._compute_score(summary, issues)
        status = self._compute_status(issues)
        return SummaryValidationResult(
            summary_id=summary.summary_id,
            status=status,
            score=score,
            issues=issues,
            checked_at=datetime.now(UTC).isoformat(),
        )

    def check_all(self, summaries: list[ActionSummary]) -> list[SummaryValidationResult]:
        """Run fidelity checks on a list of ActionSummary objects."""
        return [self.check(s) for s in summaries]

    def _check_facts(self, summary: ActionSummary, issues: list[SummaryValidationIssue]) -> None:
        for i, fact in enumerate(summary.facts):
            if not fact.evidence_ids:
                issues.append(
                    SummaryValidationIssue(
                        kind="missing_evidence_id",
                        message=f"facts[{i}]: no evidence_ids provided",
                    )
                )
            elif self._evidence_ids:
                missing = [eid for eid in fact.evidence_ids if eid not in self._evidence_ids]
                if missing:
                    safe_ids = ", ".join(missing[:3])
                    issues.append(
                        SummaryValidationIssue(
                            kind="ungrounded_fact",
                            message=(
                                f"facts[{i}]: {len(missing)} evidence_id(s) not found"
                                f" in records ({safe_ids})"
                            ),
                        )
                    )
                else:
                    texts = [
                        self._evidence_text_by_id[eid]
                        for eid in fact.evidence_ids
                        if eid in self._evidence_text_by_id
                    ]
                    if texts and not self._fact_supported_by_evidence(fact.text, texts):
                        safe_ids = ", ".join(fact.evidence_ids[:3])
                        issues.append(
                            SummaryValidationIssue(
                                kind="ungrounded_fact",
                                message=(
                                    f"facts[{i}]: fact text not supported by evidence"
                                    f" ids ({safe_ids})"
                                ),
                            )
                        )

            m = _UNCERTAINTY_PATTERN.search(fact.text)
            if m:
                issues.append(
                    SummaryValidationIssue(
                        kind="hypothesis_as_fact",
                        message=(
                            f"facts[{i}]: uncertainty language detected ({m.group()!r});"
                            " consider moving to hypotheses"
                        ),
                    )
                )

    def _check_actions_done(
        self, summary: ActionSummary, issues: list[SummaryValidationIssue]
    ) -> None:
        for i, action in enumerate(summary.actions_done):
            outcome_lower = action.outcome.strip().lower()
            status_lower = action.status.strip().lower()
            is_failure = outcome_lower in _FAILURE_OUTCOMES or status_lower in _FAILURE_OUTCOMES

            if is_failure:
                cmd = (action.command or action.target or "").strip().lower()
                if cmd:
                    in_failed = any(
                        cmd in fa.action.strip().lower() or fa.action.strip().lower() in cmd
                        for fa in summary.failed_attempts
                    )
                    if not in_failed:
                        issues.append(
                            SummaryValidationIssue(
                                kind="failed_action_misclassified",
                                message=(
                                    f"actions_done[{i}]: outcome/status indicates failure"
                                    " but action is not tracked in failed_attempts"
                                ),
                            )
                        )
            else:
                cmd = (action.command or action.target or "").strip().lower()
                if cmd:
                    for j, fa in enumerate(summary.failed_attempts):
                        fa_lower = fa.action.strip().lower()
                        if fa_lower and (cmd == fa_lower or cmd in fa_lower or fa_lower in cmd):
                            issues.append(
                                SummaryValidationIssue(
                                    kind="failed_action_misclassified",
                                    message=(
                                        f"actions_done[{i}]: recorded as successful"
                                        f" but failed_attempts[{j}] records this action"
                                        " as failed"
                                    ),
                                )
                            )
                            break

    def _check_raw_leakage(
        self, summary: ActionSummary, issues: list[SummaryValidationIssue]
    ) -> None:
        """Flag prompt-visible fields that contain raw stdout/stderr/secret/path leakage."""
        for i, fact in enumerate(summary.facts):
            if has_sensitive_content(fact.text):
                issues.append(
                    SummaryValidationIssue(
                        kind="raw_output_in_field",
                        message=f"facts[{i}].text contains raw output / secret / home path",
                    )
                )
        for i, hyp in enumerate(summary.hypotheses):
            if has_sensitive_content(hyp.text):
                issues.append(
                    SummaryValidationIssue(
                        kind="raw_output_in_field",
                        message=f"hypotheses[{i}].text contains raw output / secret / home path",
                    )
                )
        for i, fa in enumerate(summary.failed_attempts):
            for field_name in ("action", "outcome"):
                value = getattr(fa, field_name, "") or ""
                if has_sensitive_content(value):
                    issues.append(
                        SummaryValidationIssue(
                            kind="raw_output_in_field",
                            message=(
                                f"failed_attempts[{i}].{field_name}"
                                " contains raw output / secret / home path"
                            ),
                        )
                    )
        for i, av in enumerate(summary.avoid):
            for field_name in ("action", "reason"):
                value = getattr(av, field_name, "") or ""
                if has_sensitive_content(value):
                    issues.append(
                        SummaryValidationIssue(
                            kind="raw_output_in_field",
                            message=(
                                f"avoid[{i}].{field_name} contains raw output / secret / home path"
                            ),
                        )
                    )
        for i, ad in enumerate(summary.actions_done):
            for field_name in ("target", "command", "outcome"):
                value = getattr(ad, field_name, "") or ""
                if has_sensitive_content(value):
                    issues.append(
                        SummaryValidationIssue(
                            kind="raw_output_in_field",
                            message=(
                                f"actions_done[{i}].{field_name}"
                                " contains raw output / secret / home path"
                            ),
                        )
                    )
        for i, nh in enumerate(summary.next_hints):
            for field_name in ("target", "reason"):
                value = getattr(nh, field_name, "") or ""
                if has_sensitive_content(value):
                    issues.append(
                        SummaryValidationIssue(
                            kind="raw_output_in_field",
                            message=(
                                f"next_hints[{i}].{field_name}"
                                " contains raw output / secret / home path"
                            ),
                        )
                    )
        if summary.validity and summary.validity.reason:
            if has_sensitive_content(summary.validity.reason):
                issues.append(
                    SummaryValidationIssue(
                        kind="raw_output_in_field",
                        message="validity.reason contains raw output / secret / home path",
                    )
                )

    def _compute_score(self, summary: ActionSummary, issues: list[SummaryValidationIssue]) -> float:
        n_total = max(
            1,
            len(summary.facts) + len(summary.failed_attempts) + len(summary.actions_done),
        )
        n_blocking = sum(1 for iss in issues if iss.kind in _BLOCKING_KINDS)
        n_non_blocking = len(issues) - n_blocking
        deduction = min(1.0, (n_blocking + n_non_blocking * 0.5) / n_total)
        return round(max(0.0, 1.0 - deduction), 4)

    def _compute_status(self, issues: list[SummaryValidationIssue]) -> str:
        if not issues:
            return "valid"
        if any(iss.kind in _BLOCKING_KINDS for iss in issues):
            return "invalid"
        return "partial"

    def _extract_evidence_text(self, record: dict[str, Any]) -> str:
        values: list[str] = []
        self._collect_text_values(record, values)
        return "\n".join(values)

    def _collect_text_values(self, value: Any, values: list[str]) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in _TEXT_FIELDS and isinstance(child, str) and child.strip():
                    values.append(child)
                elif isinstance(child, dict | list):
                    self._collect_text_values(child, values)
        elif isinstance(value, list):
            for child in value:
                if isinstance(child, dict | list):
                    self._collect_text_values(child, values)

    def _fact_supported_by_evidence(self, fact_text: str, evidence_texts: list[str]) -> bool:
        fact_norm = " ".join(self._tokens(fact_text))
        evidence_norm = " ".join(self._tokens("\n".join(evidence_texts)))
        if not fact_norm or not evidence_norm:
            return True
        if fact_norm in evidence_norm:
            return True
        fact_tokens = set(fact_norm.split())
        evidence_tokens = set(evidence_norm.split())
        overlap = fact_tokens & evidence_tokens
        return len(overlap) / len(fact_tokens) >= 0.6

    def _tokens(self, text: str) -> list[str]:
        return [
            word
            for word in _WORD_PATTERN.findall(text.lower())
            if len(word) > 2 and word not in _STOP_WORDS
        ]


__all__ = ["SummaryFidelityChecker"]
