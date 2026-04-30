"""Sanitizer placeholder for event and dataset text."""

from __future__ import annotations


def sanitize_text(text: str | None) -> str:
    """Return a safe string placeholder until redaction rules are implemented."""
    return text or ""
