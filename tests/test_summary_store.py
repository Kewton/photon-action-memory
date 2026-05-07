"""Tests for SummaryStore and SummaryRetriever (Issue #68)."""

from __future__ import annotations

from pathlib import Path

import pytest

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionSummary,
    Fact,
    Validity,
)
from photon_action_memory.memory.retrieval import SummaryRetriever
from photon_action_memory.memory.staleness import StalenessContext
from photon_action_memory.memory.summary_store import SummaryStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _summary(
    summary_id: str = "sum-1",
    *,
    repo_id: str | None = "repo-a",
    task_signature: str | None = None,
    validity_status: str = "valid",
    fact_text: str = "the thing is true",
) -> ActionSummary:
    return ActionSummary(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        summary_id=summary_id,
        repo_id=repo_id,
        task_signature=task_signature,
        facts=[Fact(text=fact_text, evidence_ids=["ev-1"], confidence=0.9)],
        validity=Validity(status=validity_status),
    )


# ---------------------------------------------------------------------------
# SummaryStore — upsert / get / resolve / search / count
# ---------------------------------------------------------------------------


def test_upsert_and_get(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        s = _summary("sum-x")
        store.upsert(s)
        result = store.get("sum-x")
    assert result is not None
    assert result.summary_id == "sum-x"
    assert result.facts[0].text == "the thing is true"


def test_get_missing_returns_none(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        assert store.get("no-such-id") is None


def test_upsert_is_idempotent(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        store.upsert(_summary("sum-x", fact_text="v1"))
        store.upsert(_summary("sum-x", fact_text="v2"))
        result = store.get("sum-x")
        count = store.count()
    assert result is not None
    assert result.facts[0].text == "v2"
    assert count == 1


def test_resolve_returns_in_input_order(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        store.upsert(_summary("sum-a"))
        store.upsert(_summary("sum-b"))
        store.upsert(_summary("sum-c"))
        results = store.resolve(["sum-c", "sum-a", "sum-b"])
    assert [r.summary_id for r in results] == ["sum-c", "sum-a", "sum-b"]


def test_resolve_skips_missing_ids(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        store.upsert(_summary("sum-real"))
        results = store.resolve(["sum-real", "sum-ghost"])
    assert len(results) == 1
    assert results[0].summary_id == "sum-real"


def test_resolve_empty_list_returns_empty(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        assert store.resolve([]) == []


def test_search_by_repo_id(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        store.upsert(_summary("sum-a", repo_id="repo-a"))
        store.upsert(_summary("sum-b", repo_id="repo-b"))
        results = store.search(repo_id="repo-a")
    assert len(results) == 1
    assert results[0].summary_id == "sum-a"


def test_search_by_task_signature(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        store.upsert(_summary("sum-a", task_signature="sig-1"))
        store.upsert(_summary("sum-b", task_signature="sig-2"))
        results = store.search(task_signature="sig-1")
    assert len(results) == 1
    assert results[0].summary_id == "sum-a"


def test_search_bounded_by_limit(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        for i in range(10):
            store.upsert(_summary(f"sum-{i}"))
        results = store.search(limit=3)
    assert len(results) == 3


def test_search_limit_below_one_raises(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        with pytest.raises(ValueError, match="limit"):
            store.search(limit=0)


def test_count_reflects_upserts(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        assert store.count() == 0
        store.upsert(_summary("sum-1"))
        store.upsert(_summary("sum-2"))
        assert store.count() == 2
        store.upsert(_summary("sum-1"))  # update, not insert
        assert store.count() == 2


def test_upsert_preserves_created_at(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        store.upsert(_summary("sum-x"))
        import sqlite3

        row1 = (
            sqlite3.connect(tmp_path / "s.sqlite")
            .execute("SELECT created_at, updated_at FROM action_summaries WHERE summary_id='sum-x'")
            .fetchone()
        )
        store.upsert(_summary("sum-x", fact_text="v2"))
        row2 = (
            sqlite3.connect(tmp_path / "s.sqlite")
            .execute("SELECT created_at, updated_at FROM action_summaries WHERE summary_id='sum-x'")
            .fetchone()
        )
    assert row1[0] == row2[0], "created_at must not change on update"
    assert row1[1] != row2[1], "updated_at must change on update"


# ---------------------------------------------------------------------------
# SummaryRetriever — resolve_candidates with staleness filtering
# ---------------------------------------------------------------------------


def test_retriever_resolve_returns_valid_summaries(tmp_path: Path) -> None:
    store = SummaryStore(tmp_path / "s.sqlite")
    store.upsert(_summary("sum-v"))
    retriever = SummaryRetriever(store)
    results = retriever.resolve_candidates(["sum-v"])
    assert len(results) == 1
    assert results[0].summary_id == "sum-v"


def test_retriever_excludes_stale(tmp_path: Path) -> None:
    store = SummaryStore(tmp_path / "s.sqlite")
    store.upsert(_summary("sum-stale", validity_status="stale"))
    store.upsert(_summary("sum-ok"))
    retriever = SummaryRetriever(store)
    results = retriever.resolve_candidates(["sum-stale", "sum-ok"])
    assert [r.summary_id for r in results] == ["sum-ok"]


def test_retriever_excludes_contradicted(tmp_path: Path) -> None:
    store = SummaryStore(tmp_path / "s.sqlite")
    store.upsert(_summary("sum-c", validity_status="contradicted"))
    retriever = SummaryRetriever(store)
    results = retriever.resolve_candidates(["sum-c"])
    assert results == []


def test_retriever_applies_staleness_context(tmp_path: Path) -> None:
    store = SummaryStore(tmp_path / "s.sqlite")
    s = _summary("sum-commit", fact_text="was valid at commit abc")
    s = s.model_copy(update={"commit": "abc123"})
    store.upsert(s)
    retriever = SummaryRetriever(store)
    ctx = StalenessContext(current_commit="def456")
    results = retriever.resolve_candidates(["sum-commit"], staleness_context=ctx)
    assert results == [], "commit mismatch should mark summary stale and exclude it"


def test_retriever_search_filters_stale(tmp_path: Path) -> None:
    store = SummaryStore(tmp_path / "s.sqlite")
    store.upsert(_summary("sum-stale", repo_id="r", validity_status="stale"))
    store.upsert(_summary("sum-ok", repo_id="r"))
    retriever = SummaryRetriever(store)
    results = retriever.search(repo_id="r")
    assert [r.summary_id for r in results] == ["sum-ok"]


def test_retriever_refuted_claim_via_context(tmp_path: Path) -> None:
    store = SummaryStore(tmp_path / "s.sqlite")
    s = _summary("sum-refuted", fact_text="the thing is true")
    store.upsert(s)
    retriever = SummaryRetriever(store)
    ctx = StalenessContext(refuted_claims=["the thing is true"])
    results = retriever.resolve_candidates(["sum-refuted"], staleness_context=ctx)
    assert results == [], "contradicted summary must be excluded"
