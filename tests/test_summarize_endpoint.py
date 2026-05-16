"""Tests for POST /v1/summarize and the hierarchical action-state ↔ context-pack
wiring required by Issue #84.

Acceptance criteria covered:
- /v1/summarize persists summaries at summary_level = turn / session / case.
- /v1/context/pack retrieves the stored summary via repo / task scoping.
- prompt-visible items are summary-only; raw events never appear.
- tokens_saved_vs_raw is observable both in the summarize response and in the
  pack's TokenBudget.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from photon_action_memory.api.schema_v2 import DEFAULT_SCHEMA_VERSION_V2
from photon_action_memory.api.server import create_app
from photon_action_memory.memory.store import SQLiteEventStore
from photon_action_memory.memory.summary_store import SummaryStore

SCHEMA_V2 = DEFAULT_SCHEMA_VERSION_V2


def _chunk(
    *,
    chunk_id: str,
    summary: str,
    outcome: str = "useful",
    repo_id: str = "photon-test",
    session_id: str = "sess-summarize-1",
    event_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_V2,
        "chunk_id": chunk_id,
        "session_id": session_id,
        "kind": "repo_search",
        "summary": summary,
        "outcome": outcome,
        "event_ids": event_ids if event_ids is not None else [f"evt-{chunk_id}"],
        "repo_id": repo_id,
        "commit": "abcdef0",
    }


def _summarize_body(
    *,
    summary_level: str,
    request_id: str = "req-sum-1",
    repo_id: str = "photon-test",
    task_signature: str | None = None,
    session_id: str = "sess-summarize-1",
    chunks: list[dict[str, Any]] | None = None,
    summary_id: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": SCHEMA_V2,
        "request_id": request_id,
        "session_id": session_id,
        "repo_id": repo_id,
        "summary_level": summary_level,
        "chunks": chunks
        or [
            _chunk(chunk_id="chunk-A", summary="auth module lives in api/server.py"),
            _chunk(
                chunk_id="chunk-B",
                summary="session store wired through SQLiteEventStore",
            ),
        ],
    }
    if task_signature is not None:
        body["task_signature"] = task_signature
    if summary_id is not None:
        body["summary_id"] = summary_id
    return body


def _pack_body(
    *,
    request_id: str = "req-pack-1",
    repo_root: str = "/tmp",
    repo_name: str = "photon-test",
    task_signature: str | None = None,
) -> dict[str, Any]:
    task: dict[str, Any] = {
        "user_request": "implement feature X",
        "mode": "act",
        "summary": "working on feature X",
    }
    body: dict[str, Any] = {
        "schema_version": SCHEMA_V2,
        "request_id": request_id,
        "agent": {"name": "codex"},
        "repo": {"root": repo_root, "name": repo_name},
        "task": task,
        "working_memory": {"touched_files": []},
        "recent_event_ids": [],
        "candidate_summary_ids": [],
        "budget": {"max_memory_tokens": 800, "max_evidence_chars": 1200},
    }
    if task_signature is not None:
        task["task_signature"] = task_signature
    return body


@pytest.mark.parametrize("level", ["turn", "session", "case"])
def test_summarize_persists_at_requested_level(level: str, tmp_path: Path) -> None:
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    app = create_app(
        SQLiteEventStore(tmp_path / "events.sqlite"),
        summary_store=summary_store,
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/summarize",
            json=_summarize_body(
                summary_level=level,
                summary_id=f"sum-{level}-001",
                task_signature=f"task-{level}",
            ),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["sidecar_status"] == "ok"
    assert body["summary"]["summary_level"] == level
    assert body["summary"]["summary_id"] == f"sum-{level}-001"
    assert body["summary"]["repo_id"] == "photon-test"
    assert body["summary"]["task_signature"] == f"task-{level}"
    assert body["tokens_saved_vs_raw"] > 0
    assert body["validation"]["summary_id"] == f"sum-{level}-001"

    stored = summary_store.get(f"sum-{level}-001")
    assert stored is not None
    assert stored.summary_level == level
    assert stored.token_cost is not None
    assert stored.token_cost.tokens_saved_vs_raw == body["tokens_saved_vs_raw"]


def test_summarize_requires_at_least_one_chunk(tmp_path: Path) -> None:
    app = create_app(
        SQLiteEventStore(tmp_path / "events.sqlite"),
        summary_store=SummaryStore(tmp_path / "summaries.sqlite"),
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/summarize",
            json={
                "schema_version": SCHEMA_V2,
                "request_id": "req-empty",
                "summary_level": "turn",
                "chunks": [],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["sidecar_status"] == "degraded"
    assert body["summary"] is None
    assert body["tokens_saved_vs_raw"] == 0
    assert body["warnings"][0]["kind"] == "summarize_input"


def test_context_pack_retrieves_session_level_summary(tmp_path: Path) -> None:
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    app = create_app(
        SQLiteEventStore(tmp_path / "events.sqlite"),
        summary_store=summary_store,
    )

    with TestClient(app) as client:
        summarize_resp = client.post(
            "/v1/summarize",
            json=_summarize_body(
                summary_level="session",
                summary_id="sum-session-pack",
                task_signature="live-codename-task",
            ),
        )
        assert summarize_resp.status_code == 200
        summary_tokens_saved = summarize_resp.json()["tokens_saved_vs_raw"]
        assert summary_tokens_saved > 0

        pack_resp = client.post(
            "/v1/context/pack",
            json=_pack_body(task_signature="live-codename-task"),
        )

    assert pack_resp.status_code == 200
    payload = pack_resp.json()
    items = payload["context_pack"]["items"]
    assert [item["id"] for item in items] == ["sum-session-pack"]
    assert items[0]["kind"] == "action_summary"
    assert "FACT:" in items[0]["text"]
    assert payload["context_pack"]["mode"] == "summary_only"
    assert payload["context_pack"]["token_budget"]["tokens_saved_vs_raw"] > 0


def test_context_pack_omits_raw_evidence_after_summarize(tmp_path: Path) -> None:
    """Even with a stored hierarchical summary, raw evidence in the pack request
    is denied and never reaches the prompt-visible items list."""
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    app = create_app(
        SQLiteEventStore(tmp_path / "events.sqlite"),
        summary_store=summary_store,
    )

    with TestClient(app) as client:
        client.post(
            "/v1/summarize",
            json=_summarize_body(
                summary_level="turn",
                summary_id="sum-turn-raw",
            ),
        )

        pack_body = _pack_body()
        pack_body["raw_evidence"] = [
            {
                "item_id": "raw-1",
                "kind": "raw_tool_log",
                "content": "raw shell output that must never reach prompt",
            }
        ]
        response = client.post("/v1/context/pack", json=pack_body)

    payload = response.json()
    items = payload["context_pack"]["items"]
    assert all(item["kind"] == "action_summary" for item in items)
    item_ids = {item["id"] for item in items}
    assert "raw-1" not in item_ids
    for item in items:
        assert "raw shell output" not in item["text"]
    omitted_ids = {entry["id"] for entry in payload["context_pack"]["omitted"]}
    assert "raw-1" in omitted_ids


def test_summarize_overrides_summary_level_when_built_at_chunk(tmp_path: Path) -> None:
    """The builder defaults to summary_level=chunk; /v1/summarize must override
    it with the request value so hierarchical retrieval has accurate metadata."""
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    app = create_app(
        SQLiteEventStore(tmp_path / "events.sqlite"),
        summary_store=summary_store,
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/summarize",
            json=_summarize_body(
                summary_level="case",
                summary_id="sum-case-override",
            ),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["summary_level"] == "case"
    stored = summary_store.get("sum-case-override")
    assert stored is not None
    assert stored.summary_level == "case"


# ---------------------------------------------------------------------------
# Issue #121 — generator telemetry (default = rule_based, LLM falls back when MLX missing)
# ---------------------------------------------------------------------------


def test_summarize_default_reports_rule_based_generator(tmp_path: Path) -> None:
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    app = create_app(
        SQLiteEventStore(tmp_path / "events.sqlite"),
        summary_store=summary_store,
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/summarize",
            json=_summarize_body(
                summary_level="turn",
                summary_id="sum-default-gen",
            ),
        )
    assert response.status_code == 200
    body = response.json()
    assert body["generator_used"] == "rule_based"
    assert body["generator_fallback_reason"] is None


def test_summarize_llm_mode_without_mlx_falls_back(tmp_path: Path) -> None:
    """With PHOTON_SUMMARY_GENERATOR=llm but no MLX installed, the response
    must report the LLM was attempted and rule-based was used as the
    fail-open fallback, with the proper enum reason."""
    from photon_action_memory.memory.summary_generator import make_summary_generator

    generator = make_summary_generator(env={"PHOTON_SUMMARY_GENERATOR": "llm"})
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    app = create_app(
        SQLiteEventStore(tmp_path / "events.sqlite"),
        summary_store=summary_store,
        summary_generator=generator,
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/summarize",
            json=_summarize_body(
                summary_level="turn",
                summary_id="sum-llm-fallback",
            ),
        )
    assert response.status_code == 200
    body = response.json()
    assert body["generator_used"] == "rule_based"
    assert body["generator_fallback_reason"] in {"mlx_unavailable", "model_unavailable"}
    assert body["status"] == "fallback_rule_based"
