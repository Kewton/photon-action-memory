"""Anvil photon integration contract tests (Issue #70 P7).

Umbrella test covering all photon-side acceptance criteria:
- Anvil shared fixtures validate against photon schema/API
- unsafe raw log fixture is not prompt-visible
- shadow/canary evaluate fixtures can be stored and aggregated
- evidence expansion safety profile (anvil_profile=True) returns no raw output
- full Anvil call sequence is valid
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionSummary,
    ContextPack,
    EvaluateRequest,
    EvidenceExpandPolicy,
    EvidenceExpandRequest,
)
from photon_action_memory.api.server import create_app
from photon_action_memory.context.pack import build_context_pack
from photon_action_memory.context.raw_policy import RawEvidenceItem
from photon_action_memory.eval.context_pack_log import aggregate_context_pack_eval
from photon_action_memory.integration.context_pack_contract import validate_call_sequence
from photon_action_memory.memory.evidence import (
    REASON_RAW_OUTPUT_DENIED_ANVIL,
    EvidenceExpander,
)
from photon_action_memory.memory.store import SQLiteEventStore
from photon_action_memory.memory.summary_store import SummaryStore

FIXTURES_V2 = Path(__file__).parent / "fixtures" / "v0.2"
FIXTURES_PHOTON = Path(__file__).parent / "fixtures" / "photon"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client(tmp_path: Path) -> TestClient:
    store = SQLiteEventStore(tmp_path / "events.sqlite")
    return TestClient(create_app(store))


def _load(directory: Path, name: str) -> object:
    return json.loads((directory / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# AC-2: Anvil shared fixtures validate against photon schema/API
# ---------------------------------------------------------------------------


def test_anvil_evaluate_shadow_fixture_validates() -> None:
    raw = _load(FIXTURES_V2, "evaluate_anvil_shadow.json")
    req = EvaluateRequest.model_validate(raw)
    assert req.context_pack_event is not None
    assert req.context_pack_event.adoption_status == "shadow_not_injected"
    assert req.agent is not None
    assert req.agent.name == "anvil"


def test_anvil_adoption_log_fixture_validates_all_statuses() -> None:
    raw = _load(FIXTURES_V2, "context_pack_adoption_log_anvil.json")
    records = raw["records"]  # type: ignore[index]
    report = aggregate_context_pack_eval(records)
    assert report.total_turns == 5
    assert report.shadow_not_injected_count == 1
    assert report.not_available_count == 1
    assert report.error_count == 1
    assert report.adopted_count == 2


def test_anvil_canary_context_pack_fixture_validates() -> None:
    raw = _load(FIXTURES_V2, "canary_context_pack.json")
    pack = ContextPack.model_validate(raw)
    assert pack.mode == "summary_only"
    # raw stdout item must be in omitted, not items
    item_ids = {item.id for item in pack.items}
    omitted_ids = {o.id for o in pack.omitted}
    assert "raw-stdout-1" in omitted_ids
    assert "raw-stdout-1" not in item_ids


def test_anvil_photon_action_summary_fixture_validates() -> None:
    raw = _load(FIXTURES_PHOTON, "anvil_action_summary.json")
    summary = ActionSummary.model_validate(raw)
    assert summary.summary_id == "anvil-sum-photon-001"
    assert summary.repo_id == "my-repo"
    assert len(summary.facts) == 2
    assert summary.validity.status == "valid"


def test_anvil_shadow_evaluate_log_fixture_validates() -> None:
    raw = _load(FIXTURES_PHOTON, "anvil_shadow_evaluate_log.json")
    records = raw["records"]  # type: ignore[index]
    report = aggregate_context_pack_eval(records)
    assert report.total_turns == 3
    assert report.shadow_not_injected_count == 1
    assert report.not_available_count == 1
    assert report.adopted_count == 1


# ---------------------------------------------------------------------------
# AC-3: unsafe raw log fixture is not prompt-visible
# ---------------------------------------------------------------------------


def test_anvil_raw_log_fixture_not_in_context_pack_items() -> None:
    raw_items = [
        RawEvidenceItem(item_id="anvil-stdout-001", kind="stdout", content="build output"),
        RawEvidenceItem(item_id="anvil-stderr-001", kind="stderr", content="warnings"),
        RawEvidenceItem(item_id="anvil-build-001", kind="build_log", content="error: compile"),
    ]
    from photon_action_memory.api.schema_v2 import ContextPackBudget

    pack, decisions = build_context_pack(
        request_id="anvil-test-001",
        session_id=None,
        repo_id="my-repo",
        summaries=[],
        budget=ContextPackBudget(max_memory_tokens=800),
        raw_items=raw_items,
    )
    assert pack.items == []
    omitted_ids = {o.id for o in pack.omitted}
    assert "anvil-stdout-001" in omitted_ids
    assert "anvil-stderr-001" in omitted_ids
    assert "anvil-build-001" in omitted_ids
    assert all(d.decision == "deny" for d in decisions)


def test_anvil_raw_log_fixture_api_returns_empty_items(tmp_path: Path) -> None:
    raw = _load(FIXTURES_PHOTON, "anvil_raw_tool_log_request.json")
    with _client(tmp_path) as client:
        resp = client.post("/v1/context/pack", json=raw)
    assert resp.status_code == 200
    data = resp.json()
    assert data["context_pack"]["items"] == []
    omitted_ids = {o["id"] for o in data["context_pack"]["omitted"]}
    assert "anvil-stdout-001" in omitted_ids
    assert "anvil-stderr-001" in omitted_ids
    assert "anvil-build-001" in omitted_ids


# ---------------------------------------------------------------------------
# AC-4: shadow/canary evaluate fixtures can be stored and aggregated
# ---------------------------------------------------------------------------


def test_anvil_shadow_evaluate_fixture_stored_in_event_store(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite")
    with TestClient(create_app(store)) as client:
        raw = _load(FIXTURES_V2, "evaluate_anvil_shadow.json")
        resp = client.post("/v1/evaluate", json=raw)
    assert resp.status_code == 200
    assert resp.json()["logged"] == 1
    assert store.count() == 1
    stored = store.list_events()[0]
    assert stored.payload["adoption_status"] == "shadow_not_injected"


def test_anvil_shadow_evaluate_multiple_fixtures_aggregate(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite")
    photon_log = _load(FIXTURES_PHOTON, "anvil_shadow_evaluate_log.json")
    records = photon_log["records"]  # type: ignore[index]
    with TestClient(create_app(store)) as client:
        for i, record in enumerate(records):
            body = {
                "schema_version": DEFAULT_SCHEMA_VERSION_V2,
                "request_id": f"anvil-eval-{i}",
                "context_pack_event": record,
            }
            resp = client.post("/v1/evaluate", json=body)
            assert resp.status_code == 200
            assert resp.json()["logged"] == 1

    assert store.count() == 3
    payloads = [e.payload for e in store.list_events()]
    statuses = {p["adoption_status"] for p in payloads}
    assert "shadow_not_injected" in statuses
    assert "adopted" in statuses
    assert "not_available" in statuses

    report = aggregate_context_pack_eval(payloads)
    assert report.total_turns == 3
    assert report.shadow_not_injected_count == 1
    assert report.not_available_count == 1
    assert report.adopted_count == 1


# ---------------------------------------------------------------------------
# AC-5: evidence expansion safety profile returns no raw output
# ---------------------------------------------------------------------------


def test_anvil_evidence_expand_safety_profile_denies_stdout() -> None:
    expander = EvidenceExpander(
        records=[
            {"evidence_id": "ev-anvil-raw", "kind": "stdout", "summary": "s", "stdout": "build log"}
        ]
    )
    policy = EvidenceExpandPolicy(allow_raw_full_output=True, anvil_profile=True)
    req = EvidenceExpandRequest(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        request_id="req-anvil",
        evidence_ids=["ev-anvil-raw"],
        policy=policy,
    )
    resp = expander.expand(req)
    assert resp.expanded == []
    assert len(resp.omitted) == 1
    assert resp.omitted[0].reason == REASON_RAW_OUTPUT_DENIED_ANVIL


def test_anvil_evidence_expand_safety_profile_allows_safe_snippet() -> None:
    expander = EvidenceExpander(
        records=[
            {
                "evidence_id": "ev-anvil-safe",
                "kind": "file_inspection",
                "summary": "type mismatch on line 42",
                "snippet": "let x: u32 = value as u32;",
            }
        ]
    )
    policy = EvidenceExpandPolicy(anvil_profile=True)
    req = EvidenceExpandRequest(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        request_id="req-anvil-safe",
        evidence_ids=["ev-anvil-safe"],
        policy=policy,
    )
    resp = expander.expand(req)
    assert len(resp.expanded) == 1
    assert resp.expanded[0].snippet == "let x: u32 = value as u32;"
    assert resp.omitted == []


# ---------------------------------------------------------------------------
# Full Anvil call sequence validation
# ---------------------------------------------------------------------------


def test_anvil_full_call_sequence_is_valid() -> None:
    violations = validate_call_sequence(["context_pack", "evidence_expand", "evaluate"])
    assert violations == []


def test_anvil_minimal_call_sequence_is_valid() -> None:
    violations = validate_call_sequence(["context_pack", "evaluate"])
    assert violations == []


def test_anvil_missing_evaluate_is_violation() -> None:
    violations = validate_call_sequence(["context_pack"])
    assert any("evaluate" in v for v in violations)


def test_anvil_missing_context_pack_is_violation() -> None:
    violations = validate_call_sequence(["evaluate"])
    assert any("context_pack" in v for v in violations)


# ---------------------------------------------------------------------------
# Summary store integration — Anvil upsert + context pack resolve
# ---------------------------------------------------------------------------


def test_anvil_summary_upsert_and_resolve_via_context_pack(tmp_path: Path) -> None:
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    event_store = SQLiteEventStore(tmp_path / "events.sqlite")
    raw_summary = _load(FIXTURES_PHOTON, "anvil_action_summary.json")
    summary = ActionSummary.model_validate(raw_summary)
    summary_store.upsert(summary)

    with TestClient(create_app(event_store, summary_store)) as client:
        body: dict[str, object] = {
            "schema_version": DEFAULT_SCHEMA_VERSION_V2,
            "request_id": "pack-resolve-001",
            "agent": {"name": "anvil", "version": "1.0.0"},
            "repo": {"root": "/workspace/my-repo", "name": "my-repo"},
            "task": {
                "user_request": "fix build",
                "mode": "act",
                "summary": "fixing build",
            },
            "working_memory": {"touched_files": []},
            "recent_event_ids": [],
            "candidate_summary_ids": ["anvil-sum-photon-001"],
            "budget": {"max_memory_tokens": 800, "max_evidence_chars": 1200},
        }
        resp = client.post("/v1/context/pack", json=body)

    assert resp.status_code == 200
    data = resp.json()
    assert data["sidecar_status"] == "ok"
    assert len(data["context_pack"]["items"]) >= 1
    item_texts = " ".join(i["text"] for i in data["context_pack"]["items"])
    assert "type mismatch" in item_texts.lower() or "u32" in item_texts
