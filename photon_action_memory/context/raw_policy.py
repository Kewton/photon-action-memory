"""Raw evidence / tool-log default-deny policy.

Raw tool output (stdout, stderr, grep output, build logs, full file content)
must not become prompt-visible ContextPack text.  This module provides the
evaluation logic; ``build_context_pack`` applies it to every raw item.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Denied kinds: every item whose kind matches is unconditionally denied.
# ---------------------------------------------------------------------------

RAW_DENIED_KINDS: frozenset[str] = frozenset(
    {
        "stdout",
        "stderr",
        "grep_output",
        "build_log",
        "file_content",
        "raw_output",
        "tool_output",
        "raw_tool_log",
        "shell_output",
        "command_output",
    }
)

_DENY_POLICY = "raw_tool_log_default_deny"

# ---------------------------------------------------------------------------
# Sensitive-content patterns
# ---------------------------------------------------------------------------

_SECRET_KV = re.compile(
    r"(?i)(?:password|passwd|secret|api[_\-]?key|access[_\-]?token"
    r"|auth[_\-]?token|private[_\-]?key)[\s]*[=:]\s*\S+"
)
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]{20,}=*")
_TOKEN_PREFIX = re.compile(
    r"(?:sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{10,}|ghs_[A-Za-z0-9]{10,}"
    r"|xox[baprs]-[A-Za-z0-9\-]{10,})"
)
_HOME_PATH = re.compile(r"/(?:home|Users|root)/[^\s,;\"']+")


@dataclass
class RawEvidenceItem:
    """A candidate raw evidence / tool-log item."""

    item_id: str
    kind: str
    content: str
    source: str | None = field(default=None)


def has_sensitive_content(text: str) -> bool:
    """Return True if *text* contains secret-like strings, home paths, or token-like values."""
    return bool(
        _SECRET_KV.search(text)
        or _BEARER.search(text)
        or _TOKEN_PREFIX.search(text)
        or _HOME_PATH.search(text)
    )


def evaluate_raw_item(item: RawEvidenceItem) -> tuple[str, str]:
    """Evaluate *item* under the raw evidence default-deny policy.

    Always returns ``("deny", reason)``.  Raw tool output is never admitted.
    """
    if item.kind in RAW_DENIED_KINDS:
        return (
            "deny",
            f"raw tool log default deny policy: kind '{item.kind}' is always denied",
        )
    if has_sensitive_content(item.content):
        return "deny", "raw tool log default deny policy: sensitive content detected"
    return "deny", "raw tool log default deny policy: raw evidence denied by default"


__all__ = [
    "RAW_DENIED_KINDS",
    "RawEvidenceItem",
    "evaluate_raw_item",
    "has_sensitive_content",
]
