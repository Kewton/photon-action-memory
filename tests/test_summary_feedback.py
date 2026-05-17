"""Tests for per-summary feedback tracking and admission demotion (Issue #87).

Acceptance criteria:
- summary_id ごとに採用回数、成功/失敗、safety outcome を追跡できる。
- S2-03 型の悪化 summary を低 confidence / disabled として扱える。
- S3-01 / S5-01 型の有効 summary を優先できる。
- feedback がなくても deterministic fallback として動作する。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionSummary,
    ContextPackBudget,
    Fact,
    Validity,
)
from photon_action_memory.api.server import create_app
from photon_action_memory.context.pack import build_context_pack
from photon_action_memory.eval.summary_feedback import (
    DISABLE_CONFIDENCE_THRESHOLD,
    MIN_ADOPTIONS_FOR_DISABLE,
    SummaryFeedbackRecord,
    classify_outcome,
    confidence,
    is_adopted,
    is_disabled,
)
from photon_action_memory.memory.store import SQLiteEventStore
from photon_action_memory.memory.summary_store import SummaryStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _summary(
    summary_id: str = "sum-1",
    *,
    repo_id: str | None = "repo-a",
    validity_status: str = "valid",
    fact_text: str = "the thing is true",
) -> ActionSummary:
    return ActionSummary(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        summary_id=summary_id,
        repo_id=repo_id,
        facts=[Fact(text=fact_text, evidence_ids=["ev-1"])],
        validity=Validity(status=validity_status),
    )


def _make_client(tmp_path: Path) -> tuple[TestClient, SQLiteEventStore, SummaryStore]:
    events = SQLiteEventStore(tmp_path / "events.sqlite")
    summaries = SummaryStore(tmp_path / "summaries.sqlite")
    return TestClient(create_app(events, summaries)), events, summaries


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_confidence_neutral_prior_for_zero_observations() -> None:
    record = SummaryFeedbackRecord(summary_id="s")
    assert confidence(record) == pytest.approx(0.5)


def test_confidence_increases_with_success() -> None:
    record = SummaryFeedbackRecord(summary_id="s", success_count=5, failure_count=0)
    assert confidence(record) > 0.8


def test_confidence_decreases_with_failure() -> None:
    record = SummaryFeedbackRecord(summary_id="s", success_count=0, failure_count=5)
    assert confidence(record) < 0.2


def test_is_disabled_for_any_safety_violation() -> None:
    record = SummaryFeedbackRecord(summary_id="s", safety_violation_count=1)
    assert is_disabled(record) is True


def test_is_disabled_after_repeated_failures() -> None:
    # 4 adoptions, all failing -> low confidence, exceeds adoption threshold
    record = SummaryFeedbackRecord(
        summary_id="s",
        adoption_count=4,
        failure_count=4,
        quality_turns=4,
    )
    assert is_disabled(record) is True


def test_is_disabled_returns_false_for_few_adoptions() -> None:
    # Below MIN_ADOPTIONS_FOR_DISABLE, even all-failure should not disable.
    record = SummaryFeedbackRecord(
        summary_id="s",
        adoption_count=MIN_ADOPTIONS_FOR_DISABLE - 1,
        failure_count=MIN_ADOPTIONS_FOR_DISABLE - 1,
        quality_turns=MIN_ADOPTIONS_FOR_DISABLE - 1,
    )
    assert is_disabled(record) is False


def test_is_disabled_returns_false_for_high_confidence() -> None:
    record = SummaryFeedbackRecord(
        summary_id="s",
        adoption_count=10,
        success_count=9,
        failure_count=1,
        quality_turns=10,
    )
    assert is_disabled(record) is False


def test_classify_outcome_excluded_status() -> None:
    is_quality, kind = classify_outcome("error", None)
    assert is_quality is False
    assert kind == "none"


def test_classify_outcome_success() -> None:
    assert classify_outcome("adopted", "success") == (True, "success")


def test_classify_outcome_failure() -> None:
    assert classify_outcome("adopted", "failure") == (True, "failure")


def test_classify_outcome_safety_violation() -> None:
    assert classify_outcome("adopted", "safety_violation") == (True, "safety")


def test_classify_outcome_none_outcome_is_failure() -> None:
    assert classify_outcome("adopted", None) == (True, "failure")


def test_is_adopted_true_for_adopted_and_partial() -> None:
    assert is_adopted("adopted") is True
    assert is_adopted("partial") is True


def test_is_adopted_false_for_ignored() -> None:
    assert is_adopted("ignored") is False


# ---------------------------------------------------------------------------
# SummaryStore record_outcomes / get_feedback
# ---------------------------------------------------------------------------


def test_record_outcomes_increments_success(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        store.record_outcomes(
            ["sum-1"],
            adoption_status="adopted",
            outcome="success",
            evidence_expand_requested=False,
        )
        rec = store.get_feedback("sum-1")
    assert rec is not None
    assert rec.adoption_count == 1
    assert rec.success_count == 1
    assert rec.failure_count == 0
    assert rec.safety_violation_count == 0
    assert rec.quality_turns == 1


def test_record_outcomes_accumulates(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        store.record_outcomes(["sum-1"], adoption_status="adopted", outcome="success")
        store.record_outcomes(["sum-1"], adoption_status="adopted", outcome="failure")
        store.record_outcomes(["sum-1"], adoption_status="adopted", outcome="success")
        rec = store.get_feedback("sum-1")
    assert rec is not None
    assert rec.adoption_count == 3
    assert rec.success_count == 2
    assert rec.failure_count == 1


def test_record_outcomes_skips_excluded_status(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        rows = store.record_outcomes(["sum-1"], adoption_status="error", outcome=None)
    assert rows == 0


def test_record_outcomes_skips_empty_list(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        assert store.record_outcomes([], adoption_status="adopted", outcome="success") == 0


def test_record_outcomes_safety_increments_safety_counter(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        store.record_outcomes(["sum-1"], adoption_status="adopted", outcome="safety_violation")
        rec = store.get_feedback("sum-1")
    assert rec is not None
    assert rec.safety_violation_count == 1
    assert rec.failure_count == 0


def test_record_outcomes_ignored_does_not_increment_adoption(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        store.record_outcomes(["sum-1"], adoption_status="ignored", outcome="failure")
        rec = store.get_feedback("sum-1")
    assert rec is not None
    assert rec.adoption_count == 0
    assert rec.quality_turns == 1
    assert rec.failure_count == 1


def test_get_feedback_map_returns_only_known_ids(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        store.record_outcomes(["sum-a"], adoption_status="adopted", outcome="success")
        result = store.get_feedback_map(["sum-a", "sum-missing"])
    assert "sum-a" in result
    assert "sum-missing" not in result


def test_get_feedback_returns_none_for_missing(tmp_path: Path) -> None:
    with SummaryStore(tmp_path / "s.sqlite") as store:
        assert store.get_feedback("nope") is None


# ---------------------------------------------------------------------------
# build_context_pack: feedback admission
# ---------------------------------------------------------------------------


def test_build_pack_disables_low_confidence_summary() -> None:
    bad = _summary("sum-bad", fact_text="alpha bravo fact")
    good = _summary("sum-good", fact_text="charlie delta fact")
    feedback = {
        "sum-bad": SummaryFeedbackRecord(
            summary_id="sum-bad",
            adoption_count=4,
            failure_count=4,
            quality_turns=4,
        ),
    }
    pack, decisions = build_context_pack(
        request_id="req-1",
        session_id=None,
        repo_id="repo-a",
        summaries=[bad, good],
        budget=ContextPackBudget(max_memory_tokens=4000),
        summary_feedback=feedback,
    )
    admitted_ids = {item.id for item in pack.items}
    assert "sum-bad" not in admitted_ids
    assert "sum-good" in admitted_ids
    deny_decisions = [d for d in decisions if d.decision == "deny"]
    assert any(d.item_id == "sum-bad" for d in deny_decisions)
    assert any("disabled by feedback" in (d.reason or "") for d in deny_decisions)


def test_build_pack_disables_summary_with_safety_violation() -> None:
    unsafe = _summary("sum-unsafe")
    feedback = {
        "sum-unsafe": SummaryFeedbackRecord(
            summary_id="sum-unsafe",
            adoption_count=1,
            safety_violation_count=1,
            quality_turns=1,
        ),
    }
    pack, decisions = build_context_pack(
        request_id="req-1",
        session_id=None,
        repo_id="repo-a",
        summaries=[unsafe],
        budget=ContextPackBudget(max_memory_tokens=4000),
        summary_feedback=feedback,
    )
    assert pack.items == []
    omitted_reasons = {o.reason for o in pack.omitted}
    assert any("safety_violation" in r for r in omitted_reasons)


def test_build_pack_prefers_high_confidence_under_tight_budget() -> None:
    """Higher-confidence summaries win the token budget vs unseen ones."""
    high = _summary("sum-high", fact_text="alpha bravo charlie delta echo")
    low_prior = _summary("sum-prior", fact_text="foxtrot golf hotel india juliet")
    feedback = {
        "sum-high": SummaryFeedbackRecord(
            summary_id="sum-high",
            adoption_count=10,
            success_count=10,
            quality_turns=10,
        ),
    }
    pack, _ = build_context_pack(
        request_id="req-1",
        session_id=None,
        repo_id="repo-a",
        summaries=[low_prior, high],
        budget=ContextPackBudget(max_memory_tokens=20),
        summary_feedback=feedback,
    )
    admitted_ids = [item.id for item in pack.items]
    assert admitted_ids[0] == "sum-high"


def test_build_pack_without_feedback_preserves_order() -> None:
    a = _summary("sum-a", fact_text="alpha fact")
    b = _summary("sum-b", fact_text="bravo fact")
    pack, _ = build_context_pack(
        request_id="req-1",
        session_id=None,
        repo_id="repo-a",
        summaries=[a, b],
        budget=ContextPackBudget(max_memory_tokens=4000),
    )
    admitted_ids = [item.id for item in pack.items]
    assert admitted_ids == ["sum-a", "sum-b"]


def test_build_pack_with_empty_feedback_map_preserves_order() -> None:
    """Deterministic fallback: empty feedback acts identically to None."""
    a = _summary("sum-a", fact_text="alpha fact")
    b = _summary("sum-b", fact_text="bravo fact")
    pack, _ = build_context_pack(
        request_id="req-1",
        session_id=None,
        repo_id="repo-a",
        summaries=[a, b],
        budget=ContextPackBudget(max_memory_tokens=4000),
        summary_feedback={},
    )
    admitted_ids = [item.id for item in pack.items]
    assert admitted_ids == ["sum-a", "sum-b"]


# ---------------------------------------------------------------------------
# /v1/evaluate + /v1/context/pack end-to-end
# ---------------------------------------------------------------------------


def test_evaluate_records_summary_outcomes(tmp_path: Path) -> None:
    client, _, summaries = _make_client(tmp_path)
    body = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "eval-1",
        "context_pack_event": {
            "context_pack_request_id": "pack-1",
            "adoption_status": "adopted",
            "summary_ids_adopted": ["sum-x"],
            "outcome": "success",
        },
    }
    response = client.post("/v1/evaluate", json=body)
    assert response.status_code == 200
    record = summaries.get_feedback("sum-x")
    assert record is not None
    assert record.success_count == 1
    assert record.adoption_count == 1


def test_evaluate_without_summary_ids_is_noop(tmp_path: Path) -> None:
    client, _, summaries = _make_client(tmp_path)
    body = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "eval-2",
        "context_pack_event": {
            "context_pack_request_id": "pack-2",
            "adoption_status": "adopted",
            "outcome": "success",
        },
    }
    response = client.post("/v1/evaluate", json=body)
    assert response.status_code == 200
    assert summaries.get_feedback_map(["any"]) == {}


def test_evaluate_safety_violation_recorded(tmp_path: Path) -> None:
    client, _, summaries = _make_client(tmp_path)
    body = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "eval-3",
        "context_pack_event": {
            "context_pack_request_id": "pack-3",
            "adoption_status": "adopted",
            "summary_ids_adopted": ["sum-unsafe"],
            "outcome": "safety_violation",
        },
    }
    response = client.post("/v1/evaluate", json=body)
    assert response.status_code == 200
    rec = summaries.get_feedback("sum-unsafe")
    assert rec is not None
    assert rec.safety_violation_count == 1
    assert is_disabled(rec) is True


def test_evaluate_then_pack_filters_disabled(tmp_path: Path) -> None:
    """End-to-end: bad outcomes accumulate, /v1/context/pack omits the summary."""
    client, _, summaries = _make_client(tmp_path)
    # Seed a summary
    summaries.upsert(_summary("sum-bad", fact_text="alpha bravo fact"))
    summaries.upsert(_summary("sum-good", fact_text="charlie delta fact"))

    # Record several failures for sum-bad (above MIN_ADOPTIONS_FOR_DISABLE).
    for i in range(MIN_ADOPTIONS_FOR_DISABLE + 1):
        client.post(
            "/v1/evaluate",
            json={
                "schema_version": DEFAULT_SCHEMA_VERSION_V2,
                "request_id": f"eval-bad-{i}",
                "context_pack_event": {
                    "context_pack_request_id": f"pack-bad-{i}",
                    "adoption_status": "adopted",
                    "summary_ids_adopted": ["sum-bad"],
                    "outcome": "failure",
                },
            },
        )

    rec = summaries.get_feedback("sum-bad")
    assert rec is not None and is_disabled(rec)
    assert confidence(rec) < DISABLE_CONFIDENCE_THRESHOLD

    pack_response = client.post(
        "/v1/context/pack",
        json={
            "schema_version": DEFAULT_SCHEMA_VERSION_V2,
            "request_id": "ctx-1",
            "agent": {"name": "anvil"},
            "repo": {"root": "/r", "name": "repo-a"},
            "task": {"user_request": "x", "mode": "act"},
            "working_memory": {},
            "candidate_summary_ids": ["sum-bad", "sum-good"],
        },
    )
    assert pack_response.status_code == 200
    body = pack_response.json()
    admitted_ids = {item["id"] for item in body["context_pack"]["items"]}
    assert "sum-bad" not in admitted_ids
    assert "sum-good" in admitted_ids


def test_evaluate_excluded_status_does_not_update_feedback(tmp_path: Path) -> None:
    client, _, summaries = _make_client(tmp_path)
    body = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "eval-err-1",
        "context_pack_event": {
            "context_pack_request_id": "pack-err",
            "adoption_status": "error",
            "summary_ids_adopted": ["sum-x"],
        },
    }
    response = client.post("/v1/evaluate", json=body)
    assert response.status_code == 200
    assert summaries.get_feedback("sum-x") is None


# ---------------------------------------------------------------------------
# Issue #126 — ranking log + feedback export end-to-end
# ---------------------------------------------------------------------------


def test_context_pack_writes_ranking_log_without_raw_text(tmp_path: Path) -> None:
    """`/v1/context/pack` populates context_pack_ranking_log with no text."""
    client, _, summaries = _make_client(tmp_path)
    summaries.upsert(_summary("sum-ranklog", fact_text="alpha foxtrot fact"))
    response = client.post(
        "/v1/context/pack",
        json={
            "schema_version": DEFAULT_SCHEMA_VERSION_V2,
            "request_id": "pack-rank-1",
            "agent": {"name": "anvil"},
            "repo": {"root": "/r", "name": "repo-a"},
            "task": {"user_request": "x", "mode": "act"},
            "working_memory": {},
            "candidate_summary_ids": ["sum-ranklog"],
        },
    )
    assert response.status_code == 200

    entries = summaries.ranking_log.iter_entries(context_pack_request_id="pack-rank-1")
    assert entries, "expected ranking log entries to be written"
    for entry in entries:
        # The ranking log is forbidden from carrying rendered prompt text.
        assert entry.kind == "action_summary"
        assert entry.position >= 0
        assert isinstance(entry.score, float)
        assert isinstance(entry.selected, bool)
        # The label is computable up front (no outcome yet → ignored/not_selected/gate).
        assert entry.label() in {
            "ignored",
            "not_selected",
            "omitted_by_gate",
        }


def test_evaluate_back_fills_ranking_log_outcome(tmp_path: Path) -> None:
    """`/v1/evaluate` writes outcome_family back to ranking_log rows."""
    client, _, summaries = _make_client(tmp_path)
    summaries.upsert(_summary("sum-feedback-flow", fact_text="bravo golf fact"))
    client.post(
        "/v1/context/pack",
        json={
            "schema_version": DEFAULT_SCHEMA_VERSION_V2,
            "request_id": "pack-rank-2",
            "agent": {"name": "anvil"},
            "repo": {"root": "/r", "name": "repo-a"},
            "task": {"user_request": "x", "mode": "act"},
            "working_memory": {},
            "candidate_summary_ids": ["sum-feedback-flow"],
        },
    )
    client.post(
        "/v1/evaluate",
        json={
            "schema_version": DEFAULT_SCHEMA_VERSION_V2,
            "request_id": "eval-flow-1",
            "context_pack_event": {
                "context_pack_request_id": "pack-rank-2",
                "adoption_status": "adopted",
                "summary_ids_adopted": ["sum-feedback-flow"],
                "outcome": "success",
            },
        },
    )

    entries = summaries.ranking_log.iter_entries(context_pack_request_id="pack-rank-2")
    matched = [e for e in entries if e.summary_id == "sum-feedback-flow"]
    assert matched, "expected outcome to be written to the matching log row"
    assert matched[0].outcome_family == "success"
    assert matched[0].label() == "adopted_success"
