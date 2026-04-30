"""Fail-open sidecar client."""

from __future__ import annotations

from typing import Any

import httpx

from photon_action_memory import SCHEMA_VERSION
from photon_action_memory.api.schema import FALLBACK_MODEL_VERSION


def fallback_response(reason: str, *, request_id: str = "") -> dict[str, object]:
    """Return the minimal shape a client can use when the sidecar is unavailable."""
    return {
        "request_id": request_id,
        "schema_version": SCHEMA_VERSION,
        "model_version": FALLBACK_MODEL_VERSION,
        "suggestions": [],
        "evidence": [],
        "warnings": [{"kind": "sidecar_unavailable", "message": reason}],
    }


class SidecarClient:
    """Small synchronous client that never blocks agent progress on suggest."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8765",
        *,
        timeout: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def health(self) -> dict[str, Any]:
        response = self._client.get("/health")
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        raise ValueError("sidecar health response was not an object")

    def record_event(self, event: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post("/v1/events", json=event)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        raise ValueError("sidecar event response was not an object")

    def suggest(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = request.get("request_id")
        try:
            response = self._client.post("/v1/suggest", json=request)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return fallback_response(str(exc), request_id=str(request_id or ""))

        if isinstance(payload, dict):
            return payload
        return fallback_response(
            "sidecar suggest response was not an object", request_id=str(request_id or "")
        )

    def __enter__(self) -> SidecarClient:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()
