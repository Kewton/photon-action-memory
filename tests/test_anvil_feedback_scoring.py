"""Anvil feedback scoring tests (Issue #70 P7).

Tests summary store integration with Anvil data:
- Anvil summaries upserted via API are retrievable
- Stale Anvil summaries are filtered before context pack
- Shadow/canary evaluate records from Anvil aggregate into adoption reports
- Summary upsert API endpoint works end-to-end
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionSummary,
    Fact,
    Validity,
)
from photon_action_memory.api.server import create_app
from photon_action_memory.eval.context_pack_log import aggregate_context_pack_eval
from photon_action_memory.memory.retrieval import SummaryRetriever
from photon_action_memory.memory.store import SQLiteEventStore
from photon_action_memory.memory.summary_store import SummaryStore

FIXTURES_PHOTON = Path(__file__).parent / "fixtures" / "photon"
FIXTURES_V2 = Path(__file__).parent / "fixtures" / "v0.2"


def _load(directory: Path, name: str) -> object:
    return json.loads((directory / name).read_text(encoding="utf-8"))


def _summary(
    summary_id: str = "anvil-sum-001",
    *,
    repo_id: str = "my-repo",
    task_signature: str = "fix-build",
    validity_status: str = "valid",
) -> ActionSummary:
    return ActionSummary(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        summary_id=summary_id,
        repo_id=repo_id,
        task_signature=task_signature,
        facts=[Fact(text="the build fix is in src/main.rs line 42", evidence_ids=["ev-1"])],
        validity=Validity(status=validity_status),
    )


# ---------------------------------------------------------------------------
# Summary upsert API endpoint
# ---------------------------------------------------------------------------


def test_anvil_summary_upsert_api_returns_stored(tmp_path: Path) -> None:
    app = create_app(
        SQLiteEventStore(tmp_path / "events.sqlite"),
        SummaryStore(tmp_path / "summaries.sqlite"),
    )
    raw_summary = _load(FIXTURES_PHOTON, "anvil_action_summary.json")
    body = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "upsert-req-001",
        "summary": raw_summary,
    }
    with TestClient(app) as client:
        resp = client.post("/v1/summary/upsert", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary_id"] == "anvil-sum-photon-001"
    assert data["status"] == "stored"


def test_anvil_summary_upsert_api_twice_is_idempotent(tmp_path: Path) -> None:
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"), summary_store)
    raw_summary = _load(FIXTURES_PHOTON, "anvil_action_summary.json")
    body = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "upsert-req-002",
        "summary": raw_summary,
    }
    with TestClient(app) as client:
        client.post("/v1/summary/upsert", json=body)
        client.post("/v1/summary/upsert", json=body)
    assert summary_store.count() == 1


# ---------------------------------------------------------------------------
# SummaryStore — Anvil-specific upsert / retrieve / filter
# ---------------------------------------------------------------------------


def test_anvil_summary_store_upsert_and_get(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        raw = _load(FIXTURES_PHOTON, "anvil_action_summary.json")
        s = ActionSummary.model_validate(raw)
        store.upsert(s)
        result = store.get("anvil-sum-photon-001")
    assert result is not None
    assert result.summary_id == "anvil-sum-photon-001"
    assert result.repo_id == "my-repo"
    assert len(result.facts) == 2


def test_anvil_summary_store_search_by_repo(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        store.upsert(_summary("sum-a", repo_id="repo-anvil"))
        store.upsert(_summary("sum-b", repo_id="repo-other"))
        results = store.search(repo_id="repo-anvil")
    assert len(results) == 1
    assert results[0].summary_id == "sum-a"


def test_anvil_summary_store_search_by_task_signature(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        store.upsert(_summary("sum-a", task_signature="fix-auth"))
        store.upsert(_summary("sum-b", task_signature="fix-build"))
        results = store.search(task_signature="fix-build")
    assert len(results) == 1
    assert results[0].summary_id == "sum-b"


# ---------------------------------------------------------------------------
# SummaryRetriever — Anvil stale filtering
# ---------------------------------------------------------------------------


def test_anvil_retriever_excludes_stale_summary(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        store.upsert(_summary("sum-stale", validity_status="stale"))
        store.upsert(_summary("sum-valid", validity_status="valid"))
        retriever = SummaryRetriever(store)
        results = retriever.resolve_candidates(["sum-stale", "sum-valid"])
    assert len(results) == 1
    assert results[0].summary_id == "sum-valid"


def test_anvil_retriever_excludes_contradicted_summary(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        store.upsert(_summary("sum-bad", validity_status="contradicted"))
        retriever = SummaryRetriever(store)
        results = retriever.resolve_candidates(["sum-bad"])
    assert results == []


def test_anvil_retriever_search_filters_stale(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        store.upsert(_summary("sum-ok", repo_id="repo-a", validity_status="valid"))
        store.upsert(_summary("sum-stale", repo_id="repo-a", validity_status="stale"))
        retriever = SummaryRetriever(store)
        results = retriever.search(repo_id="repo-a")
    ids = {r.summary_id for r in results}
    assert "sum-ok" in ids
    assert "sum-stale" not in ids


# ---------------------------------------------------------------------------
# Aggregate shadow/canary evaluate records from stored events
# ---------------------------------------------------------------------------


def test_anvil_shadow_evaluate_records_aggregate_after_store(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite")
    app = create_app(store)
    photon_log = _load(FIXTURES_PHOTON, "anvil_shadow_evaluate_log.json")
    records = photon_log["records"]  # type: ignore[index]

    with TestClient(app) as client:
        for i, record in enumerate(records):
            body = {
                "schema_version": DEFAULT_SCHEMA_VERSION_V2,
                "request_id": f"scoring-eval-{i}",
                "context_pack_event": record,
            }
            client.post("/v1/evaluate", json=body)

    payloads = [e.payload for e in store.list_events()]
    report = aggregate_context_pack_eval(payloads)
    assert report.total_turns == 3
    assert report.shadow_not_injected_count == 1
    assert report.not_available_count == 1
    assert report.adopted_count == 1
    assert report.adoption_rate == pytest.approx(1 / 3)


def test_anvil_adoption_log_fixture_full_aggregate(tmp_path: Path) -> None:
    raw = _load(FIXTURES_V2, "context_pack_adoption_log_anvil.json")
    report = aggregate_context_pack_eval(raw["records"])  # type: ignore[index]
    assert report.total_turns == 5
    assert report.adopted_count == 2
    assert report.shadow_not_injected_count == 1
    assert report.not_available_count == 1
    assert report.error_count == 1
    # adoption_rate = (adopted + partial) / total = 2/5
    assert report.adoption_rate == pytest.approx(2 / 5)


def test_anvil_summary_fixture_validity_is_valid() -> None:
    raw = _load(FIXTURES_PHOTON, "anvil_action_summary.json")
    s = ActionSummary.model_validate(raw)
    assert s.validity.status == "valid"
    assert s.token_cost is not None
    assert s.token_cost.tokens_saved_vs_raw > 0
