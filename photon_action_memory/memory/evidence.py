"""Evidence expander: resolve evidence_id values into sanitized snippets."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    EvidenceExpandRequest,
    EvidenceExpandResponse,
    ExpandedEvidence,
    Locator,
    OmittedEvidence,
)
from photon_action_memory.context.raw_policy import RAW_DENIED_KINDS
from photon_action_memory.memory.sanitizer import sanitize_text_with_report

logger = logging.getLogger(__name__)

# Fields that represent selected concise content (preferred).
_CONCISE_FIELDS: tuple[str, ...] = ("snippet",)
# Fields that carry raw full output, subject to default-deny.
_RAW_FIELDS: tuple[str, ...] = ("stdout", "stderr")

# Stable omit reason strings — Anvil renderer can rely on these being constant.
REASON_NOT_FOUND = "evidence_id not found"
REASON_NOT_IN_SELECTION = "evidence_id not in selected_evidence_ids"
REASON_RAW_OUTPUT_DENIED = "raw output denied by policy"
REASON_RAW_OUTPUT_DENIED_ANVIL = "raw output denied: anvil profile"
REASON_NO_CONTENT = "no expandable content available"
REASON_BUDGET_EXHAUSTED = "max_total_chars budget exhausted"


@dataclass
class _Candidate:
    """Internal structured view of a candidate evidence record."""

    evidence_id: str
    kind: str
    summary: str
    concise_text: str | None
    raw_text: str | None
    locator: Locator | None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_locator(record: dict[str, Any]) -> Locator | None:
    raw_loc = record.get("locator")
    if isinstance(raw_loc, dict):
        file_val = raw_loc.get("file")
        ls = raw_loc.get("line_start")
        le = raw_loc.get("line_end")
        cmd = raw_loc.get("command")
    else:
        file_val = record.get("file")
        ls = record.get("line_start")
        le = record.get("line_end")
        cmd = record.get("command")

    if all(v is None for v in (file_val, ls, le, cmd)):
        return None

    return Locator(
        file=str(file_val) if file_val is not None else None,
        line_start=_to_int(ls),
        line_end=_to_int(le),
        command=str(cmd) if cmd is not None else None,
    )


def _build_candidate(record: dict[str, Any]) -> _Candidate | None:
    eid = record.get("evidence_id")
    if eid is None:
        eid = record.get("event_id")
    if not isinstance(eid, str) or not eid:
        return None

    kind_raw = record.get("kind")
    kind = str(kind_raw) if kind_raw is not None else "unknown"
    summary_raw = record.get("summary")
    summary = str(summary_raw) if summary_raw is not None else ""

    is_raw_kind = kind in RAW_DENIED_KINDS

    # Selected concise content: snippet is always concise. For raw-output
    # kinds, text/content fields are treated as raw unless an explicit snippet
    # is supplied.
    concise_text: str | None = None
    for fname in _CONCISE_FIELDS:
        val = record.get(fname)
        if isinstance(val, str) and val.strip():
            concise_text = val
            break
    if concise_text is None and not is_raw_kind:
        for fname in ("text", "content"):
            val = record.get(fname)
            if isinstance(val, str) and val.strip():
                concise_text = val
                break

    # Raw full output: stdout/stderr and text/content for raw-output kinds.
    raw_text: str | None = None
    raw_field_list = _RAW_FIELDS + (("text", "content") if is_raw_kind else ())
    for fname in raw_field_list:
        val = record.get(fname)
        if isinstance(val, str) and val.strip():
            raw_text = val
            break

    return _Candidate(
        evidence_id=eid,
        kind=kind,
        summary=summary,
        concise_text=concise_text,
        raw_text=raw_text,
        locator=_extract_locator(record),
    )


class EvidenceExpander:
    """Expands evidence_id values into the smallest useful sanitized snippets."""

    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        self._index: dict[str, _Candidate] = {}
        for record in records or []:
            candidate = _build_candidate(record)
            if candidate is not None and candidate.evidence_id not in self._index:
                self._index[candidate.evidence_id] = candidate

    def expand(self, request: EvidenceExpandRequest) -> EvidenceExpandResponse:
        budget = request.budget
        policy = request.policy
        max_per = budget.max_chars_per_evidence
        max_total = budget.max_total_chars
        selection: frozenset[str] | None = (
            frozenset(request.selected_evidence_ids)
            if request.selected_evidence_ids is not None
            else None
        )

        expanded: list[ExpandedEvidence] = []
        omitted: list[OmittedEvidence] = []
        total_chars = 0

        for evidence_id in request.evidence_ids:
            if max_total is not None and total_chars >= max_total:
                omitted.append(
                    OmittedEvidence(
                        evidence_id=evidence_id,
                        reason=REASON_BUDGET_EXHAUSTED,
                    )
                )
                continue

            if selection is not None and evidence_id not in selection:
                omitted.append(
                    OmittedEvidence(
                        evidence_id=evidence_id,
                        reason=REASON_NOT_IN_SELECTION,
                    )
                )
                continue

            candidate = self._index.get(evidence_id)
            if candidate is None:
                omitted.append(
                    OmittedEvidence(evidence_id=evidence_id, reason=REASON_NOT_FOUND)
                )
                continue

            if candidate.concise_text is not None:
                raw_snippet = candidate.concise_text
            elif candidate.raw_text is not None:
                if policy.anvil_profile:
                    omitted.append(
                        OmittedEvidence(
                            evidence_id=evidence_id,
                            reason=REASON_RAW_OUTPUT_DENIED_ANVIL,
                        )
                    )
                    logger.warning(
                        "evidence %r omitted: raw output denied by anvil profile", evidence_id
                    )
                    continue
                if not policy.allow_raw_full_output:
                    omitted.append(
                        OmittedEvidence(
                            evidence_id=evidence_id,
                            reason=REASON_RAW_OUTPUT_DENIED,
                        )
                    )
                    logger.warning("evidence %r omitted: raw output denied by policy", evidence_id)
                    continue
                raw_snippet = candidate.raw_text
            else:
                omitted.append(
                    OmittedEvidence(
                        evidence_id=evidence_id,
                        reason=REASON_NO_CONTENT,
                    )
                )
                continue

            # Enforce per-evidence char limit, capped by remaining total budget.
            char_limit = max_per
            if max_total is not None:
                remaining = max_total - total_chars
                char_limit = min(char_limit, remaining)

            truncated = len(raw_snippet) > char_limit
            snippet = raw_snippet[:char_limit] if truncated else raw_snippet

            redaction_status: str | None = None
            if policy.redact_again:
                result = sanitize_text_with_report(snippet)
                snippet = result.text
                redaction_status = "redacted" if result.report.counts else "clean"

            total_chars += len(snippet)

            expanded.append(
                ExpandedEvidence(
                    evidence_id=evidence_id,
                    kind=candidate.kind,
                    summary=candidate.summary,
                    snippet=snippet,
                    locator=candidate.locator,
                    redaction_status=redaction_status,
                    truncated=truncated,
                )
            )

        return EvidenceExpandResponse(
            schema_version=DEFAULT_SCHEMA_VERSION_V2,
            request_id=request.request_id,
            expanded=expanded,
            omitted=omitted,
        )


__all__ = [
    "EvidenceExpander",
    "REASON_BUDGET_EXHAUSTED",
    "REASON_NOT_FOUND",
    "REASON_NOT_IN_SELECTION",
    "REASON_NO_CONTENT",
    "REASON_RAW_OUTPUT_DENIED",
    "REASON_RAW_OUTPUT_DENIED_ANVIL",
]
