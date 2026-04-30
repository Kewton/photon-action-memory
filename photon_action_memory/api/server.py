"""FastAPI sidecar entrypoint placeholder."""

from __future__ import annotations


def health_payload() -> dict[str, str]:
    """Return a minimal health payload without importing FastAPI yet."""
    return {"status": "ok"}
