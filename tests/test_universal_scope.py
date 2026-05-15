"""Universal applicability scope tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionSummary,
    ContextPackRequest,
    Fact,
    UniversalFilters,
    UniversalMetadata,
    Validity,
)
from photon_action_memory.api.server import create_app, detect_universal_filters
from photon_action_memory.cli.seed_add import build_seed_payload
from photon_action_memory.memory.store import SQLiteEventStore
from photon_action_memory.memory.summary_store import SummaryStore


def _fact(text: str) -> Fact:
    return Fact(text=text, evidence_ids=["ev-1"], confidence=0.9)


def _summary(
    summary_id: str,
    *,
    repo_id: str | None = "photon-test",
    task_signature: str | None = None,
    facts: list[Fact] | None = None,
) -> ActionSummary:
    return ActionSummary(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        summary_id=summary_id,
        session_id="sess-universal",
        repo_id=repo_id,
        task_signature=task_signature,
        facts=facts or [_fact(f"{summary_id} fact")],
        validity=Validity(status="valid"),
    )


def _universal_summary(
    summary_id: str,
    *,
    metadata: UniversalMetadata,
    fact_text: str | None = None,
) -> ActionSummary:
    return _summary(
        summary_id,
        repo_id="__common__",
        task_signature="unrelated-task",
        facts=[_fact(fact_text or f"{summary_id} universal fact")],
    ).model_copy(
        update={
            "schema_version": "action-memory.v0.3",
            "applicability_scope": "universal",
            "universal_metadata": metadata,
        }
    )


def _pack_request(*, user_request: str, touched_files: list[str] | None = None) -> dict:  # type: ignore[type-arg]
    return {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "req-universal",
        "agent": {"name": "codex"},
        "repo": {"root": "/tmp/photon-test", "name": "photon-test"},
        "task": {
            "user_request": user_request,
            "mode": "act",
            "summary": "working on unrelated task",
            "task_signature": "different-task",
        },
        "working_memory": {"touched_files": touched_files or []},
        "recent_event_ids": [],
        "candidate_summary_ids": [],
        "budget": {"max_memory_tokens": 800, "max_evidence_chars": 1200},
    }


def test_action_summary_defaults_to_repo_applicability_scope() -> None:
    summary = _summary("sum-default")

    assert summary.applicability_scope == "repo"
    assert summary.universal_metadata is None


def test_summary_store_search_universal_filters_metadata(tmp_path: Path) -> None:
    store = SummaryStore(tmp_path / "summaries.sqlite")
    python_seed = _universal_summary(
        "universal-python",
        metadata=UniversalMetadata(language=["python"], severity="info"),
    )
    git_seed = _universal_summary(
        "universal-git",
        metadata=UniversalMetadata(tool=["git"], severity="critical"),
    )
    store.upsert(python_seed)
    store.upsert(git_seed)
    store.upsert(_summary("repo-only", facts=[_fact("repo-only fact")]))

    python_results = store.search_universal(filters=UniversalFilters(language=["python"]))
    git_results = store.search_universal(filters=UniversalFilters(tool=["git"]))

    assert [summary.summary_id for summary in python_results] == ["universal-python"]
    assert [summary.summary_id for summary in git_results] == ["universal-git"]


def test_detect_universal_filters_from_task_text_and_files() -> None:
    request = ContextPackRequest.model_validate(
        _pack_request(
            user_request="Fix a pytest failure in a FastAPI route and commit it with git.",
            touched_files=["app/api.py", "tests/test_api.py"],
        )
    )

    filters = detect_universal_filters(request)

    assert "python" in filters.language
    assert "pytest" in filters.framework
    assert "fastapi" in filters.framework
    assert "git" in filters.tool


def test_context_pack_injects_universal_seed_across_task_signature(tmp_path: Path) -> None:
    store = SummaryStore(tmp_path / "summaries.sqlite")
    store.upsert(
        _universal_summary(
            "universal-pytest",
            metadata=UniversalMetadata(language=["python"], framework=["pytest"]),
            fact_text="pytest -v -x is useful for focused failure reproduction",
        )
    )
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"), summary_store=store)
    with TestClient(app) as client:
        response = client.post(
            "/v1/context/pack",
            json=_pack_request(
                user_request="Fix the failing pytest test.",
                touched_files=["tests/test_widget.py"],
            ),
        )

    assert response.status_code == 200
    payload = response.json()["context_pack"]
    assert [item["id"] for item in payload["items"]] == ["universal-pytest"]
    assert "pytest -v -x" in payload["items"][0]["text"]


def test_universal_seed_stage_limits_to_five_items(tmp_path: Path) -> None:
    store = SummaryStore(tmp_path / "summaries.sqlite")
    for index in range(6):
        store.upsert(
            _universal_summary(
                f"universal-python-{index}",
                metadata=UniversalMetadata(language=["python"], token_budget_cap=100),
            )
        )
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"), summary_store=store)
    with TestClient(app) as client:
        response = client.post(
            "/v1/context/pack",
            json=_pack_request(user_request="Edit Python code.", touched_files=["src/app.py"]),
        )

    assert response.status_code == 200
    items = response.json()["context_pack"]["items"]
    assert len(items) == 5


def test_universal_seed_over_per_seed_token_cap_is_not_injected(tmp_path: Path) -> None:
    store = SummaryStore(tmp_path / "summaries.sqlite")
    store.upsert(
        _universal_summary(
            "universal-too-large",
            metadata=UniversalMetadata(language=["python"], token_budget_cap=10),
            fact_text="large universal context " * 50,
        )
    )
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"), summary_store=store)
    with TestClient(app) as client:
        response = client.post(
            "/v1/context/pack",
            json=_pack_request(user_request="Edit Python code.", touched_files=["src/app.py"]),
        )

    assert response.status_code == 200
    assert response.json()["context_pack"]["items"] == []


def test_seed_add_builds_universal_payload() -> None:
    summary = _summary("sum-cli").model_dump(mode="json")

    payload = build_seed_payload(
        summary,
        request_id="req-cli",
        scope="universal",
        metadata_json='{"language":["python"],"framework":["pytest"],"severity":"warning"}',
        repo_id="__common__",
        task_signature=None,
        summary_id="sum-cli-universal",
    )

    body = payload["summary"]
    assert payload["request_id"] == "req-cli"
    assert body["summary_id"] == "sum-cli-universal"
    assert body["applicability_scope"] == "universal"
    assert body["universal_metadata"]["language"] == ["python"]
    assert body["universal_metadata"]["severity"] == "warning"
