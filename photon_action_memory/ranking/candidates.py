"""Deterministic candidate extraction helpers."""

from __future__ import annotations

import re

_PATH_RE = re.compile(
    r"(?<![\w./-])"
    r"((?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+"
    r"|[A-Za-z0-9_.-]+\.(?:py|rs|js|ts|tsx|jsx|md|toml|yaml|yml|json|txt|sh|sql))"
    r"(?::\d+(?::\d+)?)?"
)

_TRAILING_PUNCTUATION = ".,;:)]}'\"`"


def extract_candidates(items: list[str]) -> list[str]:
    """Deduplicate candidate strings while preserving input order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def extract_file_paths(text: str) -> list[str]:
    """Extract stable file path candidates from free-form event text."""
    candidates: list[str] = []
    for match in _PATH_RE.finditer(text):
        candidate = match.group(1).strip().rstrip(_TRAILING_PUNCTUATION)
        if _is_safe_path_candidate(candidate):
            candidates.append(candidate)
    return extract_candidates(candidates)


def _is_safe_path_candidate(candidate: str) -> bool:
    lowered = candidate.lower()
    if any(part in lowered for part in ("secret", "token", "password", "credential")):
        return False
    return bool(candidate and not candidate.startswith(("-", ".")))
