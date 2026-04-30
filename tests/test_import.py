from __future__ import annotations

import photon_action_memory
from photon_action_memory.api.client import fallback_response
from photon_action_memory.api.server import health_payload
from photon_action_memory.ranking.candidates import extract_candidates
from photon_action_memory.ranking.fallback import rank_candidates


def test_package_metadata() -> None:
    assert photon_action_memory.__version__ == "0.1.0"
    assert photon_action_memory.SCHEMA_VERSION == "action-memory.v1"


def test_placeholder_health_payload() -> None:
    assert health_payload() == {"status": "ok", "schema_version": "action-memory.v1"}


def test_placeholder_fail_open_response() -> None:
    payload = fallback_response("timeout")
    assert payload["suggestions"] == []
    assert payload["evidence"] == []
    assert payload["warnings"] == [{"kind": "sidecar_unavailable", "message": "timeout"}]


def test_deterministic_candidate_helpers() -> None:
    candidates = extract_candidates(["a.py", "b.py", "a.py", ""])
    assert candidates == ["a.py", "b.py"]
    assert rank_candidates(candidates, limit=1) == ["a.py"]
