"""Fail-open sidecar client placeholder."""

from __future__ import annotations


def fallback_response(reason: str) -> dict[str, object]:
    """Return the minimal shape a client can use when the sidecar is unavailable."""
    return {"suggestions": [], "warnings": [{"kind": "sidecar_unavailable", "message": reason}]}
