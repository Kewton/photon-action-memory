"""Warning and fallback guard helpers."""

from __future__ import annotations

import re
from collections import Counter

from photon_action_memory.api.schema import SuggestRequest, WarningMessage

_DESTRUCTIVE_COMMAND_RE = re.compile(
    r"(^|\s)(rm\s+-[^\n;]*[rf]|sudo\s+rm|git\s+reset\s+--hard|"
    r"git\s+clean\s+-[^\n;]*[fd]|mkfs|dd\s+if=|chmod\s+-R\s+777)\b"
)

_EDIT_TERMS = (
    "edit",
    "change",
    "modify",
    "implement",
    "fix",
    "update",
    "patch",
    "write",
)


def is_destructive_command(command: str) -> bool:
    """Return true when a shell command should never be suggested."""
    return bool(_DESTRUCTIVE_COMMAND_RE.search(command.strip().lower()))


def fallback_warnings(request: SuggestRequest) -> list[WarningMessage]:
    """Build deterministic non-fatal warnings for fallback suggestions."""
    warnings: list[WarningMessage] = [
        WarningMessage(
            kind="model_unavailable",
            message=(
                "PHOTON model scoring is unavailable; deterministic fallback suggestions were used."
            ),
        )
    ]
    warnings.extend(repeated_action_warnings(request))
    if needs_missing_evidence_warning(request):
        warnings.append(
            WarningMessage(
                kind="missing_evidence",
                message="Edit-like request has insufficient supporting evidence.",
            )
        )
    return warnings


def repeated_action_warnings(request: SuggestRequest) -> list[WarningMessage]:
    """Warn when recent read/search actions repeat the same target or query."""
    keys: list[tuple[str, str]] = []
    for event in request.recent_events:
        payload = event.model_dump()
        action = _action_name(payload)
        if action not in {"read", "search"}:
            continue
        subject = _action_subject(payload)
        if subject:
            keys.append((action, subject))

    warnings: list[WarningMessage] = []
    for (action, subject), count in sorted(Counter(keys).items()):
        if count > 1:
            warnings.append(
                WarningMessage(
                    kind="repeat_failure",
                    message=f"Recent {action} action repeated {subject!r} {count} times.",
                )
            )
    return warnings


def needs_missing_evidence_warning(request: SuggestRequest) -> bool:
    """Detect edit-like requests that lack recent or remembered evidence."""
    text = " ".join(
        part
        for part in (
            request.task.user_request,
            request.task.summary or "",
            request.working_memory.active_task or "",
        )
        if part
    ).lower()
    if not any(term in text for term in _EDIT_TERMS):
        return False
    if request.working_memory.evidence_ids:
        return False
    return not any((event.evidence_id or event.summary.strip()) for event in request.recent_events)


def _action_name(payload: dict[str, object]) -> str:
    raw = " ".join(
        str(payload.get(key) or "") for key in ("kind", "action", "tool", "type", "summary")
    ).lower()
    if "read" in raw or "open" in raw or "inspect" in raw:
        return "read"
    if "search" in raw or "rg" in raw or "grep" in raw:
        return "search"
    return ""


def _action_subject(payload: dict[str, object]) -> str:
    for key in ("target", "path", "file", "query", "command"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(payload.get("summary") or "").strip()
