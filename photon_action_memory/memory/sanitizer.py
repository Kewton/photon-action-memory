"""Sanitizers for event and dataset text.

The full sanitizer milestone can add richer reports and domain-specific rules.
This module keeps the storage boundary private by redacting common secret and
absolute-path patterns before data is persisted.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}\b", re.IGNORECASE)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(api[_-]?key|token|password|secret)\s*[:=]\s*['\"]?[^'\"\s,;}]+",
    re.IGNORECASE,
)
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_=-]{32,}\b")
_USER_PATH_RE = re.compile(r"(?<!\w)/(Users|home)/([^/\s'\",;)]+)((?:/[^/\s'\",;)]+)*)?")
_TMP_PATH_RE = re.compile(r"(?<!\w)/tmp((?:/[^/\s'\",;)]+)*)?")

SanitizedPayload = dict[str, Any]


def sanitize_text(text: str | None) -> str:
    """Return text with common secrets and absolute user paths redacted."""
    if text is None:
        return ""

    sanitized = _ANSI_ESCAPE_RE.sub("", text)
    sanitized = _CONTROL_CHAR_RE.sub("", sanitized)
    sanitized = _EMAIL_RE.sub("[EMAIL]", sanitized)
    sanitized = _BEARER_RE.sub("Bearer [REDACTED_SECRET]", sanitized)
    sanitized = _SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}=[REDACTED_SECRET]",
        sanitized,
    )
    sanitized = _OPENAI_KEY_RE.sub("[REDACTED_SECRET]", sanitized)
    sanitized = _LONG_TOKEN_RE.sub("[REDACTED_SECRET]", sanitized)
    sanitized = _USER_PATH_RE.sub(lambda match: f"[USER_PATH]{match.group(3) or ''}", sanitized)
    sanitized = _TMP_PATH_RE.sub(lambda match: f"[TMP_PATH]{match.group(1) or ''}", sanitized)
    return sanitized


def sanitize_event_payload(payload: Mapping[str, Any]) -> SanitizedPayload:
    """Return a sanitized copy of an event payload safe for local persistence."""
    sanitized = _sanitize_value(payload)
    if not isinstance(sanitized, dict):
        msg = "event payload must sanitize to a JSON object"
        raise TypeError(msg)

    redaction_status = sanitized.get("redaction_status")
    if not isinstance(redaction_status, str) or not redaction_status:
        sanitized["redaction_status"] = (
            "redacted" if _sanitize_value(payload) != _plain_json_value(payload) else "clean"
        )
    return sanitized


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, Mapping):
        return {str(key): _sanitize_value(child) for key, child in value.items()}
    if _is_sequence(value):
        return [_sanitize_value(child) for child in value]
    if value is None or isinstance(value, bool | int | float):
        return value
    return sanitize_text(str(value))


def _plain_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json_value(child) for key, child in value.items()}
    if _is_sequence(value):
        return [_plain_json_value(child) for child in value]
    if value is None or isinstance(value, str | bool | int | float):
        return value
    return str(value)


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)
