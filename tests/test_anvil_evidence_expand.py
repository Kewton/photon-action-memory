"""Anvil evidence expansion safety profile tests (Issue #70 P7).

Tests /v1/evidence/expand with anvil_profile=True:
- Raw stdout/stderr always denied regardless of allow_raw_full_output
- Safe concise snippets are returned
- selected_evidence_ids filtering works with Anvil profile
- Stable reason strings are preserved
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    EvidenceExpandBudget,
    EvidenceExpandPolicy,
    EvidenceExpandRequest,
)
from photon_action_memory.api.server import create_app
from photon_action_memory.memory.evidence import (
    REASON_NOT_IN_SELECTION,
    REASON_RAW_OUTPUT_DENIED_ANVIL,
    EvidenceExpander,
)
from photon_action_memory.memory.store import SQLiteEventStore

FIXTURES_V2 = Path(__file__).parent / "fixtures" / "v0.2"


def _rec(evidence_id: str, **kwargs: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "evidence_id": evidence_id,
        "kind": kwargs.pop("kind", "file_inspection"),
        "summary": kwargs.pop("summary", "test summary"),
    }
    record.update(kwargs)
    return record


def _req(
    evidence_ids: list[str],
    *,
    policy: EvidenceExpandPolicy | None = None,
    budget: EvidenceExpandBudget | None = None,
    selected_ids: list[str] | None = None,
) -> EvidenceExpandRequest:
    return EvidenceExpandRequest(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        request_id="req-anvil-expand",
        evidence_ids=evidence_ids,
        selected_evidence_ids=selected_ids,
        budget=budget or EvidenceExpandBudget(),
        policy=policy or EvidenceExpandPolicy(anvil_profile=True),
    )


# ---------------------------------------------------------------------------
# anvil_profile denies raw output regardless of allow_raw_full_output
# ---------------------------------------------------------------------------


def test_anvil_profile_denies_stdout_with_allow_raw_true() -> None:
    expander = EvidenceExpander(
        records=[_rec("ev-anvil-out", kind="stdout", stdout="cargo build output")]
    )
    resp = expander.expand(
        _req(
            ["ev-anvil-out"],
            policy=EvidenceExpandPolicy(allow_raw_full_output=True, anvil_profile=True),
        )
    )
    assert resp.expanded == []
    assert len(resp.omitted) == 1
    assert resp.omitted[0].reason == REASON_RAW_OUTPUT_DENIED_ANVIL


def test_anvil_profile_denies_stderr_with_allow_raw_true() -> None:
    expander = EvidenceExpander(records=[_rec("ev-anvil-err", kind="stderr", stderr="error trace")])
    resp = expander.expand(
        _req(
            ["ev-anvil-err"],
            policy=EvidenceExpandPolicy(allow_raw_full_output=True, anvil_profile=True),
        )
    )
    assert resp.expanded == []
    assert resp.omitted[0].reason == REASON_RAW_OUTPUT_DENIED_ANVIL


def test_anvil_profile_denies_build_log() -> None:
    expander = EvidenceExpander(
        records=[_rec("ev-anvil-build", kind="build_log", content="BUILD FAILED")]
    )
    resp = expander.expand(_req(["ev-anvil-build"]))
    assert resp.expanded == []
    assert len(resp.omitted) == 1
    assert resp.omitted[0].reason == REASON_RAW_OUTPUT_DENIED_ANVIL


def test_anvil_profile_denies_grep_output() -> None:
    expander = EvidenceExpander(
        records=[_rec("ev-anvil-grep", kind="grep_output", content="src/main.rs:42: let x = 1;")]
    )
    resp = expander.expand(_req(["ev-anvil-grep"]))
    assert resp.expanded == []
    assert resp.omitted[0].reason == REASON_RAW_OUTPUT_DENIED_ANVIL


def test_anvil_profile_denies_file_content() -> None:
    expander = EvidenceExpander(
        records=[_rec("ev-anvil-fc", kind="file_content", content="fn main() {}")]
    )
    resp = expander.expand(_req(["ev-anvil-fc"]))
    assert resp.expanded == []
    assert resp.omitted[0].reason == REASON_RAW_OUTPUT_DENIED_ANVIL


# ---------------------------------------------------------------------------
# anvil_profile allows safe concise snippets
# ---------------------------------------------------------------------------


def test_anvil_profile_allows_file_inspection_snippet() -> None:
    expander = EvidenceExpander(
        records=[
            _rec("ev-anvil-snip", kind="file_inspection", snippet="let x: u32 = value as u32;")
        ]
    )
    resp = expander.expand(_req(["ev-anvil-snip"]))
    assert len(resp.expanded) == 1
    assert resp.expanded[0].snippet == "let x: u32 = value as u32;"
    assert resp.omitted == []


def test_anvil_profile_allows_edit_attempt_snippet() -> None:
    expander = EvidenceExpander(
        records=[
            _rec("ev-anvil-edit", kind="edit_attempt", snippet="Changed line 42 from i32 to u32")
        ]
    )
    resp = expander.expand(_req(["ev-anvil-edit"]))
    assert len(resp.expanded) == 1
    assert resp.omitted == []


def test_anvil_profile_snippet_is_sanitized() -> None:
    secret = "token=sk-abc123def456ghi789jkl012"
    expander = EvidenceExpander(records=[_rec("ev-anvil-sec", snippet=secret)])
    resp = expander.expand(_req(["ev-anvil-sec"]))
    assert len(resp.expanded) == 1
    snippet = resp.expanded[0].snippet or ""
    assert "sk-abc123" not in snippet
    assert "[REDACTED" in snippet


# ---------------------------------------------------------------------------
# selected_evidence_ids + anvil_profile
# ---------------------------------------------------------------------------


def test_anvil_profile_selected_ids_allows_listed() -> None:
    expander = EvidenceExpander(records=[_rec("ev-allowed", snippet="safe code")])
    resp = expander.expand(_req(["ev-allowed"], selected_ids=["ev-allowed"]))
    assert len(resp.expanded) == 1


def test_anvil_profile_selected_ids_omits_unlisted() -> None:
    expander = EvidenceExpander(records=[_rec("ev-blocked", snippet="safe code")])
    resp = expander.expand(_req(["ev-blocked"], selected_ids=["ev-other"]))
    assert resp.expanded == []
    assert len(resp.omitted) == 1
    assert resp.omitted[0].reason == REASON_NOT_IN_SELECTION


def test_anvil_profile_selected_ids_with_raw_blocked_by_anvil() -> None:
    expander = EvidenceExpander(records=[_rec("ev-raw-sel", kind="stdout", stdout="build log")])
    resp = expander.expand(
        _req(
            ["ev-raw-sel"],
            policy=EvidenceExpandPolicy(allow_raw_full_output=True, anvil_profile=True),
            selected_ids=["ev-raw-sel"],
        )
    )
    # selected_evidence_ids check passes (it's in the list), but anvil_profile blocks raw
    assert resp.expanded == []
    assert resp.omitted[0].reason == REASON_RAW_OUTPUT_DENIED_ANVIL


# ---------------------------------------------------------------------------
# API endpoint with anvil_profile policy
# ---------------------------------------------------------------------------


def _api_body(
    evidence_ids: list[str],
    *,
    extra_records: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
    selected_ids: list[str] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "req-anvil-api",
        "evidence_ids": evidence_ids,
        "budget": {"max_chars_per_evidence": 1200},
        "policy": policy or {"anvil_profile": True, "redact_again": True},
    }
    if extra_records is not None:
        body["evidence_records"] = extra_records
    if selected_ids is not None:
        body["selected_evidence_ids"] = selected_ids
    return body


def test_api_anvil_profile_denies_stdout(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    records = [
        {
            "evidence_id": "ev-anvil-api-out",
            "kind": "stdout",
            "summary": "s",
            "stdout": "build output",
        }
    ]
    with TestClient(app) as client:
        resp = client.post(
            "/v1/evidence/expand", json=_api_body(["ev-anvil-api-out"], extra_records=records)
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["expanded"] == []
    assert data["omitted"][0]["reason"] == REASON_RAW_OUTPUT_DENIED_ANVIL


def test_api_anvil_profile_allows_safe_snippet(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    records = [
        {
            "evidence_id": "ev-anvil-api-safe",
            "kind": "file_inspection",
            "summary": "s",
            "snippet": "def fix(): pass",
        }
    ]
    with TestClient(app) as client:
        resp = client.post(
            "/v1/evidence/expand", json=_api_body(["ev-anvil-api-safe"], extra_records=records)
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["expanded"]) == 1
    assert data["expanded"][0]["snippet"] == "def fix(): pass"


def test_api_anvil_profile_stable_reason_raw_denied(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    records = [
        {"evidence_id": "ev-anvil-stable", "kind": "stdout", "summary": "s", "stdout": "log"}
    ]
    body = _api_body(
        ["ev-anvil-stable"],
        extra_records=records,
        policy={"allow_raw_full_output": True, "redact_again": True, "anvil_profile": True},
    )
    with TestClient(app) as client:
        resp = client.post("/v1/evidence/expand", json=body)
    assert resp.status_code == 200
    assert resp.json()["omitted"][0]["reason"] == "raw output denied: anvil profile"


def test_api_anvil_profile_selected_ids_filtering(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    records = [
        {"evidence_id": "ev-anvil-in", "kind": "file_inspection", "summary": "s", "snippet": "yes"},
        {"evidence_id": "ev-anvil-out", "kind": "file_inspection", "summary": "s", "snippet": "no"},
    ]
    body = _api_body(
        ["ev-anvil-in", "ev-anvil-out"],
        extra_records=records,
        selected_ids=["ev-anvil-in"],
    )
    with TestClient(app) as client:
        resp = client.post("/v1/evidence/expand", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["expanded"]) == 1
    assert data["expanded"][0]["evidence_id"] == "ev-anvil-in"
    assert len(data["omitted"]) == 1
    assert data["omitted"][0]["reason"] == "evidence_id not in selected_evidence_ids"
