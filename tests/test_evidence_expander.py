"""Tests for EvidenceExpander and POST /v1/evidence/expand.

Acceptance criteria covered:
- selected sanitized snippet returned by evidence_id
- full raw output is default-denied
- max_chars_per_evidence truncates snippets
- max_total_chars limits total output and omits remaining IDs with reasons
- sanitizer re-runs before response; secrets and home paths not visible
- omitted reason for missing evidence IDs and denied raw output
- locator line range / command returned when present
- API route works with evidence_records extras and store-backed events
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    EvidenceExpandBudget,
    EvidenceExpandPolicy,
    EvidenceExpandRequest,
)
from photon_action_memory.api.server import create_app
from photon_action_memory.memory.evidence import EvidenceExpander
from photon_action_memory.memory.store import SQLiteEventStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _req(
    evidence_ids: list[str],
    *,
    budget: EvidenceExpandBudget | None = None,
    policy: EvidenceExpandPolicy | None = None,
) -> EvidenceExpandRequest:
    return EvidenceExpandRequest(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        request_id="req-test",
        evidence_ids=evidence_ids,
        budget=budget or EvidenceExpandBudget(),
        policy=policy or EvidenceExpandPolicy(),
    )


def _rec(evidence_id: str, **kwargs: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "evidence_id": evidence_id,
        "kind": kwargs.pop("kind", "file_inspection"),
        "summary": kwargs.pop("summary", "test summary"),
    }
    record.update(kwargs)
    return record


# ---------------------------------------------------------------------------
# Snippet selection
# ---------------------------------------------------------------------------


def test_snippet_field_returned_by_evidence_id() -> None:
    expander = EvidenceExpander(records=[_rec("ev-1", snippet="auth.py line 42")])
    resp = expander.expand(_req(["ev-1"]))
    assert len(resp.expanded) == 1
    assert resp.expanded[0].evidence_id == "ev-1"
    assert resp.expanded[0].snippet == "auth.py line 42"
    assert resp.omitted == []


def test_text_field_used_as_concise_snippet() -> None:
    expander = EvidenceExpander(records=[_rec("ev-2", text="concise finding")])
    resp = expander.expand(_req(["ev-2"]))
    assert len(resp.expanded) == 1
    assert resp.expanded[0].snippet == "concise finding"


def test_content_field_used_for_non_raw_kind() -> None:
    expander = EvidenceExpander(
        records=[_rec("ev-3", kind="file_inspection", content="def foo(): pass")]
    )
    resp = expander.expand(_req(["ev-3"]))
    assert len(resp.expanded) == 1
    assert "def foo" in (resp.expanded[0].snippet or "")


def test_snippet_preferred_over_text() -> None:
    expander = EvidenceExpander(records=[_rec("ev-pri", snippet="snippet wins", text="text loses")])
    resp = expander.expand(_req(["ev-pri"]))
    assert resp.expanded[0].snippet == "snippet wins"


def test_event_id_fallback_for_evidence_id() -> None:
    records: list[dict[str, Any]] = [
        {"event_id": "ev-evt", "kind": "file_inspection", "summary": "s", "snippet": "code"}
    ]
    expander = EvidenceExpander(records=records)
    resp = expander.expand(_req(["ev-evt"]))
    assert len(resp.expanded) == 1
    assert resp.expanded[0].evidence_id == "ev-evt"


# ---------------------------------------------------------------------------
# Default deny for raw full output
# ---------------------------------------------------------------------------


def test_stdout_default_denied() -> None:
    expander = EvidenceExpander(records=[_rec("ev-raw", kind="stdout", stdout="Build output")])
    resp = expander.expand(_req(["ev-raw"]))
    assert resp.expanded == []
    assert len(resp.omitted) == 1
    assert "denied" in resp.omitted[0].reason


def test_stderr_default_denied() -> None:
    expander = EvidenceExpander(records=[_rec("ev-err", kind="stderr", stderr="Error trace")])
    resp = expander.expand(_req(["ev-err"]))
    assert resp.expanded == []
    assert "denied" in resp.omitted[0].reason


def test_content_on_raw_kind_default_denied() -> None:
    expander = EvidenceExpander(
        records=[_rec("ev-fc", kind="file_content", content="raw file body")]
    )
    resp = expander.expand(_req(["ev-fc"]))
    assert resp.expanded == []
    assert "denied" in resp.omitted[0].reason


def test_text_on_raw_kind_default_denied() -> None:
    expander = EvidenceExpander(records=[_rec("ev-text-raw", kind="stdout", text="raw log")])
    resp = expander.expand(_req(["ev-text-raw"]))
    assert resp.expanded == []
    assert "denied" in resp.omitted[0].reason


def test_raw_output_allowed_when_policy_permits() -> None:
    expander = EvidenceExpander(records=[_rec("ev-allow", kind="stdout", stdout="output")])
    policy = EvidenceExpandPolicy(allow_raw_full_output=True)
    resp = expander.expand(_req(["ev-allow"], policy=policy))
    assert len(resp.expanded) == 1
    assert resp.expanded[0].snippet == "output"


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------


def test_max_chars_per_evidence_truncates() -> None:
    # Use safe text (short words, no patterns that trigger sanitizer redaction).
    snippet = "Hello World! " * 200  # ~2600 chars, no long-secret match
    expander = EvidenceExpander(records=[_rec("ev-big", snippet=snippet)])
    budget = EvidenceExpandBudget(max_chars_per_evidence=100)
    resp = expander.expand(_req(["ev-big"], budget=budget))
    assert len(resp.expanded) == 1
    assert resp.expanded[0].truncated is True
    assert len(resp.expanded[0].snippet or "") == 100


def test_snippet_not_truncated_when_under_limit() -> None:
    expander = EvidenceExpander(records=[_rec("ev-small", snippet="short")])
    budget = EvidenceExpandBudget(max_chars_per_evidence=100)
    resp = expander.expand(_req(["ev-small"], budget=budget))
    assert resp.expanded[0].truncated is False
    assert resp.expanded[0].snippet == "short"


def test_max_total_chars_limits_and_omits_remaining() -> None:
    # Use safe text so sanitizer does not change the snippet length.
    base = "the quick brown fox. " * 30  # ~630 chars per record, no redaction
    records = [
        _rec("ev-a", snippet=base),
        _rec("ev-b", snippet=base),
        _rec("ev-c", snippet=base),
    ]
    expander = EvidenceExpander(records=records)
    budget = EvidenceExpandBudget(max_chars_per_evidence=1200, max_total_chars=600)
    resp = expander.expand(_req(["ev-a", "ev-b", "ev-c"], budget=budget))

    total = sum(len(e.snippet or "") for e in resp.expanded)
    assert total <= 600
    assert len(resp.omitted) >= 1
    assert any("budget" in o.reason for o in resp.omitted)


def test_max_total_chars_exhausted_before_second_item() -> None:
    records = [_rec("ev-x", snippet="a" * 100), _rec("ev-y", snippet="b" * 100)]
    expander = EvidenceExpander(records=records)
    budget = EvidenceExpandBudget(max_chars_per_evidence=200, max_total_chars=50)
    resp = expander.expand(_req(["ev-x", "ev-y"], budget=budget))
    assert len(resp.expanded) == 1
    assert resp.expanded[0].truncated is True
    assert len(resp.omitted) == 1
    assert resp.omitted[0].evidence_id == "ev-y"
    assert "budget" in resp.omitted[0].reason


# ---------------------------------------------------------------------------
# Sanitizer re-run
# ---------------------------------------------------------------------------


def test_sanitizer_strips_secret_from_snippet() -> None:
    secret = "token=sk-abc123def456ghi789jkl012"
    expander = EvidenceExpander(records=[_rec("ev-sec", snippet=secret)])
    resp = expander.expand(_req(["ev-sec"]))
    assert len(resp.expanded) == 1
    snippet = resp.expanded[0].snippet or ""
    assert "sk-abc123" not in snippet
    assert "[REDACTED" in snippet


def test_sanitizer_strips_absolute_home_path() -> None:
    expander = EvidenceExpander(
        records=[_rec("ev-path", snippet="file at /Users/alice/secret/config.py")]
    )
    resp = expander.expand(_req(["ev-path"]))
    assert len(resp.expanded) == 1
    snippet = resp.expanded[0].snippet or ""
    assert "/Users/alice" not in snippet


def test_redaction_status_is_set_after_sanitization() -> None:
    expander = EvidenceExpander(records=[_rec("ev-clean", snippet="clean text")])
    resp = expander.expand(_req(["ev-clean"]))
    assert resp.expanded[0].redaction_status in ("clean", "redacted")


def test_redaction_status_is_none_when_redact_again_false() -> None:
    expander = EvidenceExpander(records=[_rec("ev-noredact", snippet="text")])
    policy = EvidenceExpandPolicy(redact_again=False)
    resp = expander.expand(_req(["ev-noredact"], policy=policy))
    assert resp.expanded[0].redaction_status is None


# ---------------------------------------------------------------------------
# Omitted reasons
# ---------------------------------------------------------------------------


def test_omitted_reason_for_missing_evidence_id() -> None:
    expander = EvidenceExpander(records=[])
    resp = expander.expand(_req(["nonexistent"]))
    assert resp.expanded == []
    assert len(resp.omitted) == 1
    assert "not found" in resp.omitted[0].reason


def test_omitted_reason_for_denied_raw_output() -> None:
    expander = EvidenceExpander(records=[_rec("ev-deny", kind="stderr", stderr="trace")])
    resp = expander.expand(_req(["ev-deny"]))
    assert len(resp.omitted) == 1
    assert "denied" in resp.omitted[0].reason


def test_omitted_reason_when_no_expandable_content() -> None:
    expander = EvidenceExpander(records=[_rec("ev-empty")])
    resp = expander.expand(_req(["ev-empty"]))
    assert len(resp.omitted) == 1
    assert "no expandable content" in resp.omitted[0].reason


# ---------------------------------------------------------------------------
# Locator
# ---------------------------------------------------------------------------


def test_locator_line_range_from_flat_fields() -> None:
    expander = EvidenceExpander(
        records=[_rec("ev-loc", snippet="def auth", file="auth.py", line_start=10, line_end=20)]
    )
    resp = expander.expand(_req(["ev-loc"]))
    loc = resp.expanded[0].locator
    assert loc is not None
    assert loc.file == "auth.py"
    assert loc.line_start == 10
    assert loc.line_end == 20


def test_locator_command_from_flat_field() -> None:
    expander = EvidenceExpander(records=[_rec("ev-cmd", snippet="output", command="ls -la")])
    resp = expander.expand(_req(["ev-cmd"]))
    loc = resp.expanded[0].locator
    assert loc is not None
    assert loc.command == "ls -la"


def test_locator_from_nested_locator_dict() -> None:
    expander = EvidenceExpander(
        records=[
            _rec(
                "ev-nested",
                snippet="code",
                locator={"file": "api.py", "line_start": 5, "line_end": 15},
            )
        ]
    )
    resp = expander.expand(_req(["ev-nested"]))
    loc = resp.expanded[0].locator
    assert loc is not None
    assert loc.file == "api.py"
    assert loc.line_start == 5
    assert loc.line_end == 15


def test_locator_is_none_when_no_location_fields() -> None:
    expander = EvidenceExpander(records=[_rec("ev-noloc", snippet="just text")])
    resp = expander.expand(_req(["ev-noloc"]))
    assert resp.expanded[0].locator is None


# ---------------------------------------------------------------------------
# Summary / kind fields
# ---------------------------------------------------------------------------


def test_kind_and_summary_included_in_expanded() -> None:
    expander = EvidenceExpander(
        records=[_rec("ev-meta", kind="edit_attempt", summary="Tried to edit auth.py", snippet="x")]
    )
    resp = expander.expand(_req(["ev-meta"]))
    item = resp.expanded[0]
    assert item.kind == "edit_attempt"
    assert item.summary == "Tried to edit auth.py"


# ---------------------------------------------------------------------------
# API integration - POST /v1/evidence/expand
# ---------------------------------------------------------------------------


def _api_body(
    evidence_ids: list[str],
    *,
    extra_records: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "req-api",
        "evidence_ids": evidence_ids,
        "budget": budget or {"max_chars_per_evidence": 1200},
        "policy": policy or {"allow_raw_full_output": False, "redact_again": True},
    }
    if extra_records is not None:
        body["evidence_records"] = extra_records
    return body


def test_api_expand_with_evidence_records_extra(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    records = [
        {
            "evidence_id": "ev-api-1",
            "kind": "file_inspection",
            "summary": "s",
            "snippet": "found it",
        }
    ]
    with TestClient(app) as client:
        resp = client.post(
            "/v1/evidence/expand", json=_api_body(["ev-api-1"], extra_records=records)
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["expanded"]) == 1
    assert data["expanded"][0]["snippet"] == "found it"
    assert data["omitted"] == []


def test_api_expand_with_store_backed_events(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite")
    store.append(
        {
            "session_id": "sess-1",
            "turn_id": "turn-1",
            "repo_id": "repo-1",
            "event_type": "file_inspection",
            "evidence_id": "ev-store-1",
            "kind": "file_inspection",
            "summary": "store evidence",
            "snippet": "def main(): pass",
        }
    )
    app = create_app(store)
    with TestClient(app) as client:
        resp = client.post("/v1/evidence/expand", json=_api_body(["ev-store-1"]))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["expanded"]) == 1
    assert data["expanded"][0]["snippet"] == "def main(): pass"


def test_api_expand_raw_denied_by_default(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    records = [
        {"evidence_id": "ev-raw-api", "kind": "stdout", "summary": "s", "stdout": "build log"}
    ]
    with TestClient(app) as client:
        resp = client.post(
            "/v1/evidence/expand", json=_api_body(["ev-raw-api"], extra_records=records)
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["expanded"] == []
    assert len(data["omitted"]) == 1
    assert "denied" in data["omitted"][0]["reason"]


def test_api_expand_missing_id_returns_omitted(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    with TestClient(app) as client:
        resp = client.post("/v1/evidence/expand", json=_api_body(["no-such-id"]))
    assert resp.status_code == 200
    data = resp.json()
    assert data["expanded"] == []
    assert len(data["omitted"]) == 1
    assert "not found" in data["omitted"][0]["reason"]


def test_api_expand_fail_open_on_error(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    with patch(
        "photon_action_memory.api.server.EvidenceExpander",
        side_effect=RuntimeError("simulated"),
    ):
        with TestClient(app) as client:
            resp = client.post("/v1/evidence/expand", json=_api_body(["ev-fail"]))
    assert resp.status_code == 200
    data = resp.json()
    assert data["expanded"] == []
    assert len(data["omitted"]) == 1
    assert "expansion error" in data["omitted"][0]["reason"]


def test_api_expand_schema_version_in_response(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    with TestClient(app) as client:
        resp = client.post("/v1/evidence/expand", json=_api_body([]))
    assert resp.status_code == 200
    assert resp.json()["schema_version"] == DEFAULT_SCHEMA_VERSION_V2
