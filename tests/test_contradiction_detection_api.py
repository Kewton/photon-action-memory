"""Integration tests for the contradiction governance API surface (Issue #110)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionDone,
    ActionSummary,
    AvoidGuidance,
    Fact,
    Validity,
)
from photon_action_memory.api.server import create_app
from photon_action_memory.cli.audit import build_contradiction_payload
from photon_action_memory.memory.store import SQLiteEventStore
from photon_action_memory.memory.summary_store import SummaryStore

REPO_ID = "audit-repo"
TASK_SIGNATURE = "audit-task"


def _summary(
    summary_id: str,
    *,
    avoid: list[AvoidGuidance] | None = None,
    actions_done: list[ActionDone] | None = None,
    facts: list[Fact] | None = None,
    validity_status: str = "valid",
) -> ActionSummary:
    return ActionSummary(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        summary_id=summary_id,
        repo_id=REPO_ID,
        task_signature=TASK_SIGNATURE,
        facts=facts or [Fact(text=f"{summary_id} fact", evidence_ids=["e1"])],
        avoid=avoid or [],
        actions_done=actions_done or [],
        validity=Validity(status=validity_status),
    )


def _seed_conflict(summary_store: SummaryStore) -> None:
    avoider = _summary(
        "audit-avoid",
        avoid=[AvoidGuidance(action="git rebase main", reason="protected branch")],
    )
    actor = _summary(
        "audit-do",
        actions_done=[
            ActionDone(
                kind="run",
                command="git rebase main",
                outcome="ok",
                status="completed",
            )
        ],
    )
    summary_store.upsert(avoider)
    summary_store.upsert(actor)


def _pack_request_body() -> dict[str, object]:
    return {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "pack-audit-1",
        "agent": {"name": "codex"},
        "repo": {"root": "/tmp/audit-repo", "name": REPO_ID},
        "task": {
            "user_request": "rebase the branch",
            "mode": "act",
            "summary": "rebasing on main",
            "task_signature": TASK_SIGNATURE,
        },
        "working_memory": {"touched_files": []},
        "recent_event_ids": [],
        "candidate_summary_ids": [],
        "budget": {"max_memory_tokens": 800, "max_evidence_chars": 1200},
    }


def test_audit_endpoint_reports_contradiction_pairs(tmp_path: Path) -> None:
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    _seed_conflict(summary_store)
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"), summary_store=summary_store)
    with TestClient(app) as client:
        response = client.post(
            "/v1/seeds/audit/contradictions",
            json={
                "schema_version": DEFAULT_SCHEMA_VERSION_V2,
                "request_id": "audit-1",
                "repo_id": REPO_ID,
                "task_signature": TASK_SIGNATURE,
                "limit": 50,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["scanned"] == 2
    pair_kinds = {pair["kind"] for pair in body["pairs"]}
    assert "avoid_vs_action" in pair_kinds
    pair_ids = {(pair["summary_a_id"], pair["summary_b_id"]) for pair in body["pairs"]}
    assert ("audit-avoid", "audit-do") in pair_ids or ("audit-do", "audit-avoid") in pair_ids


def test_context_pack_emits_contradiction_warning(tmp_path: Path) -> None:
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    _seed_conflict(summary_store)
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"), summary_store=summary_store)
    with TestClient(app) as client:
        response = client.post("/v1/context/pack", json=_pack_request_body())

    assert response.status_code == 200
    pack = response.json()["context_pack"]
    warning_kinds = {warning["kind"] for warning in pack["warnings"]}
    assert "contradiction_detected" in warning_kinds


def test_marking_summary_contradicted_removes_warning(tmp_path: Path) -> None:
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    avoider = _summary(
        "audit-avoid",
        avoid=[AvoidGuidance(action="git rebase main", reason="protected branch")],
        validity_status="contradicted",
    )
    actor = _summary(
        "audit-do",
        actions_done=[
            ActionDone(
                kind="run",
                command="git rebase main",
                outcome="ok",
                status="completed",
            )
        ],
    )
    summary_store.upsert(avoider)
    summary_store.upsert(actor)
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"), summary_store=summary_store)
    with TestClient(app) as client:
        response = client.post("/v1/context/pack", json=_pack_request_body())

    assert response.status_code == 200
    pack = response.json()["context_pack"]
    warning_kinds = {warning["kind"] for warning in pack["warnings"]}
    assert "contradiction_detected" not in warning_kinds


def test_marking_summary_needs_review_keeps_warning(tmp_path: Path) -> None:
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    avoider = _summary(
        "audit-avoid",
        avoid=[AvoidGuidance(action="git rebase main", reason="protected branch")],
        validity_status="needs_review",
    )
    actor = _summary(
        "audit-do",
        actions_done=[
            ActionDone(
                kind="run",
                command="git rebase main",
                outcome="ok",
                status="completed",
            )
        ],
    )
    summary_store.upsert(avoider)
    summary_store.upsert(actor)
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"), summary_store=summary_store)
    with TestClient(app) as client:
        response = client.post("/v1/context/pack", json=_pack_request_body())

    assert response.status_code == 200
    pack = response.json()["context_pack"]
    warning_kinds = {warning["kind"] for warning in pack["warnings"]}
    assert "contradiction_detected" in warning_kinds


def test_audit_cli_payload_builder_includes_filters() -> None:
    payload = build_contradiction_payload(
        request_id="cli-req",
        repo_id=REPO_ID,
        task_signature=TASK_SIGNATURE,
        limit=42,
    )

    assert payload["request_id"] == "cli-req"
    assert payload["repo_id"] == REPO_ID
    assert payload["task_signature"] == TASK_SIGNATURE
    assert payload["limit"] == 42
    assert payload["schema_version"] == "action-memory.v0.2"


def test_audit_cli_payload_builder_omits_unset_filters() -> None:
    payload = build_contradiction_payload(
        request_id="cli-req",
        repo_id=None,
        task_signature=None,
        limit=10,
    )

    assert "repo_id" not in payload
    assert "task_signature" not in payload
    assert payload["limit"] == 10


def test_action_summary_accepts_needs_review_validity_status() -> None:
    summary = _summary("needs-review-1", validity_status="needs_review")
    assert summary.validity.status == "needs_review"
