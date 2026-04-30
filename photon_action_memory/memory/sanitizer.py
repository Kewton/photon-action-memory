"""Text and path sanitization helpers for event memory inputs."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REDACTED_SECRET = "[REDACTED_SECRET]"
REDACTED_EMAIL = "[EMAIL]"

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?P<key>api(?:[_-]|\s)?key|apikey|secret|token|access[_-]?token|"
    r"refresh[_-]?token|password|passwd|bearer)\b"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<quote>['\"]?)"
    r"(?P<value>[A-Za-z0-9_\-./+=:]{8,})"
    r"(?P=quote)"
)
BEARER_VALUE_RE = re.compile(r"(?i)\b(?P<prefix>bearer\s+)(?P<value>[A-Za-z0-9_\-./+=:]{12,})\b")
LONG_SECRET_RE = re.compile(r"\b(?:sk-[A-Za-z0-9_\-]{16,}|[A-Za-z0-9_\-]{32,})\b")
URL_TOKEN_RE = re.compile(r"(?i)([?&](?:token|key|secret|signature|sig)=)[^&\s]+")
ABS_PATH_RE = re.compile(r"(?P<path>/(?:Users|home|var|tmp|private|opt)/[^\s'\"`),;]+)")

SanitizedPayload = dict[str, Any]


@dataclass
class RedactionReport:
    """Counters suitable for sanitizer reports and exporter stats."""

    counts: Counter[str] = field(default_factory=Counter)

    def inc(self, key: str, amount: int = 1) -> None:
        self.counts[key] += amount

    def as_dict(self) -> dict[str, int]:
        return dict(self.counts)


@dataclass(frozen=True)
class SanitizedText:
    """Sanitized text plus redaction counters."""

    text: str
    report: RedactionReport


def sanitize_text(
    text: str | None,
    *,
    workspace_roots: Iterable[str] = (),
    max_chars: int | None = None,
) -> str:
    """Return text safe enough to store in event memory or exported datasets."""
    return sanitize_text_with_report(
        text,
        workspace_roots=workspace_roots,
        max_chars=max_chars,
    ).text


def sanitize_text_with_report(
    text: str | None,
    *,
    workspace_roots: Iterable[str] = (),
    max_chars: int | None = None,
) -> SanitizedText:
    """Return sanitized text and a report of redaction counts."""
    report = RedactionReport()
    if not text:
        return SanitizedText(text="", report=report)

    out = ANSI_RE.sub("", text)
    out = "".join(ch if ch in {"\n", "\t"} or not is_control_char(ch) else " " for ch in out)

    out = SECRET_ASSIGNMENT_RE.sub(lambda match: _replace_secret_assignment(match, report), out)
    out = BEARER_VALUE_RE.sub(lambda match: _replace_bearer_value(match, report), out)
    out = LONG_SECRET_RE.sub(lambda match: _replace_long_secret(match, report), out)

    out, email_count = EMAIL_RE.subn(REDACTED_EMAIL, out)
    report.inc("email", email_count)

    out, url_token_count = URL_TOKEN_RE.subn(r"\1" + REDACTED_SECRET, out)
    report.inc("url_token", url_token_count)

    out = normalize_absolute_paths(out, workspace_roots=workspace_roots, report=report)

    if max_chars is not None and len(out) > max_chars:
        report.inc("truncated_text")
        out = out[:max_chars] + "\n...[truncated]"

    return SanitizedText(text=out, report=report)


def sanitize_event_payload(payload: Mapping[str, Any]) -> SanitizedPayload:
    """Return a sanitized copy of an event payload safe for local persistence."""
    sanitized = _sanitize_payload_value(payload)
    if not isinstance(sanitized, dict):
        msg = "event payload must sanitize to a JSON object"
        raise TypeError(msg)

    if not isinstance(sanitized.get("redaction_status"), str):
        sanitized["redaction_status"] = (
            "redacted" if sanitized != _plain_json_value(payload) else "clean"
        )
    return sanitized


def filter_safe_path_candidates(
    candidates: Iterable[str],
    *,
    workspace_roots: Iterable[str] = (),
) -> list[str]:
    """Drop secret-bearing path candidates and normalize retained absolute paths."""
    safe: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = sanitize_path_candidate(candidate, workspace_roots=workspace_roots)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        safe.append(normalized)
    return safe


def sanitize_path_candidate(
    candidate: str | None,
    *,
    workspace_roots: Iterable[str] = (),
) -> str | None:
    """Return a safe path candidate or ``None`` when it contains secret material."""
    if not candidate:
        return None
    path = candidate.strip()
    if not path or contains_secret(path):
        return None

    return normalize_absolute_paths(
        path,
        workspace_roots=workspace_roots,
        report=RedactionReport(),
    )


def contains_secret(text: str) -> bool:
    """Return whether text contains a secret pattern that should not be stored as-is."""
    return bool(
        SECRET_ASSIGNMENT_RE.search(text)
        or BEARER_VALUE_RE.search(text)
        or _contains_unapproved_long_secret(text)
        or URL_TOKEN_RE.search(text)
    )


def normalize_absolute_paths(
    text: str,
    *,
    workspace_roots: Iterable[str] = (),
    report: RedactionReport | None = None,
) -> str:
    """Normalize sensitive absolute paths without leaving raw local prefixes."""
    roots = [root.rstrip("/") for root in workspace_roots if root.rstrip("/")]

    def repl(match: re.Match[str]) -> str:
        raw = match.group("path")
        if report is not None:
            report.inc("absolute_path")
        for root in roots:
            if raw == root:
                return "."
            prefix = root + "/"
            if raw.startswith(prefix):
                return raw[len(prefix) :]
        return "[ABS_PATH]/" + Path(raw).name

    return ABS_PATH_RE.sub(repl, text)


def is_control_char(ch: str) -> bool:
    return (ord(ch) < 32 or ord(ch) == 127) and ch not in {"\n", "\t"}


def looks_like_hex_digest(value: str) -> bool:
    return bool(re.fullmatch(r"[a-fA-F0-9]{32,64}", value))


def looks_like_uuid(value: str) -> bool:
    return bool(
        re.fullmatch(
            r"[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}",
            value,
        )
    )


def _sanitize_payload_value(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, Mapping):
        return {str(key): _sanitize_payload_value(child) for key, child in value.items()}
    if _is_sequence(value):
        return [_sanitize_payload_value(child) for child in value]
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


def _replace_secret_assignment(match: re.Match[str], report: RedactionReport) -> str:
    report.inc("secret_assignment")
    return f"{match.group('key')}{match.group('sep')}{REDACTED_SECRET}"


def _replace_bearer_value(match: re.Match[str], report: RedactionReport) -> str:
    report.inc("bearer_value")
    return f"{match.group('prefix')}{REDACTED_SECRET}"


def _replace_long_secret(match: re.Match[str], report: RedactionReport) -> str:
    value = match.group(0)
    if looks_like_hex_digest(value) or looks_like_uuid(value):
        return value
    report.inc("long_secret_like")
    return REDACTED_SECRET


def _contains_unapproved_long_secret(text: str) -> bool:
    for match in LONG_SECRET_RE.finditer(text):
        value = match.group(0)
        if looks_like_hex_digest(value) or looks_like_uuid(value):
            continue
        return True
    return False
