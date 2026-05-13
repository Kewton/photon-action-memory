"""Tests for context pack admission pipeline and POST /v1/context/pack.

Acceptance criteria covered:
- summary-only ContextPack can be returned
- ContextAdmissionDecision can be returned
- max_memory_tokens is enforced
- tokens_saved_vs_raw can be calculated
- stale / ungrounded / duplicated items can be omitted
- sidecar failure allows the agent path to fail open
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionSummary,
    AvoidGuidance,
    ContextPackBudget,
    Fact,
    FailedAttempt,
    Hypothesis,
    TokenCost,
    Validity,
)
from photon_action_memory.api.server import create_app
from photon_action_memory.context.admission import ContextAdmissionController
from photon_action_memory.context.budget import TokenBudgetTracker
from photon_action_memory.context.pack import build_context_pack
from photon_action_memory.context.render import estimate_tokens, render_summary
from photon_action_memory.memory.sanitizer import REDACTED_SECRET
from photon_action_memory.memory.store import SQLiteEventStore
from photon_action_memory.memory.summary_store import SummaryStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_summary(
    summary_id: str = "sum-aaa",
    *,
    repo_id: str | None = None,
    task_signature: str | None = None,
    facts: list[Fact] | None = None,
    hypotheses: list[Hypothesis] | None = None,
    failed_attempts: list[FailedAttempt] | None = None,
    avoid: list[AvoidGuidance] | None = None,
    validity_status: str = "valid",
    token_cost: TokenCost | None = None,
) -> ActionSummary:
    return ActionSummary(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        summary_id=summary_id,
        session_id="sess-1",
        repo_id=repo_id,
        task_signature=task_signature,
        facts=facts or [],
        hypotheses=hypotheses or [],
        failed_attempts=failed_attempts or [],
        avoid=avoid or [],
        validity=Validity(status=validity_status),
        token_cost=token_cost,
    )


def _fact(text: str, evidence_id: str = "ev-1") -> Fact:
    return Fact(text=text, evidence_ids=[evidence_id], confidence=0.9)


def _hypothesis(text: str) -> Hypothesis:
    return Hypothesis(text=text, confidence=0.5, status="open")


def _failed(action: str) -> FailedAttempt:
    return FailedAttempt(action=action, outcome="error", evidence_ids=[])


# ---------------------------------------------------------------------------
# render helpers
# ---------------------------------------------------------------------------


def test_render_summary_includes_facts_and_hypotheses() -> None:
    summary = _make_summary(
        facts=[_fact("auth module exists")],
        hypotheses=[_hypothesis("performance bottleneck in parser")],
    )
    text = render_summary(summary)
    assert "FACT: auth module exists" in text
    assert "HYPOTHESIS: performance bottleneck in parser" in text


def test_render_summary_empty_returns_empty_string() -> None:
    summary = _make_summary()
    assert render_summary(summary) == ""


def test_render_summary_masks_prompt_visible_secrets_and_paths() -> None:
    summary = _make_summary(
        facts=[
            _fact(
                "token=sk-secretvalue1234567890 and file /Users/example/private/project/config.toml"
            )
        ],
        failed_attempts=[
            FailedAttempt(
                action="curl -H 'Authorization: Bearer abcdefghijklmnop1234567890'",
                outcome="failed",
                evidence_ids=[],
            )
        ],
        avoid=[
            AvoidGuidance(
                action="open /Users/example/private/project/.env",
                reason="contains API_KEY=abcdefghi123456789",
                evidence_ids=[],
            )
        ],
    )

    text = render_summary(summary)

    assert REDACTED_SECRET in text
    assert "sk-secretvalue1234567890" not in text
    assert "abcdefghijklmnop1234567890" not in text
    assert "abcdefghi123456789" not in text
    assert "/Users/example" not in text
    assert "[ABS_PATH]/config.toml" in text


def test_estimate_tokens_minimum_is_one() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("x") == 1


def test_estimate_tokens_scales_with_length() -> None:
    assert estimate_tokens("a" * 400) == 100


# ---------------------------------------------------------------------------
# budget
# ---------------------------------------------------------------------------


def test_token_budget_tracker_fits_within_limit() -> None:
    tracker = TokenBudgetTracker(max_tokens=100)
    assert tracker.fits(100)
    assert not tracker.fits(101)


def test_token_budget_tracker_enforces_max_memory_tokens() -> None:
    tracker = TokenBudgetTracker(max_tokens=50)
    tracker.consume(40)
    assert tracker.fits(10)
    assert not tracker.fits(11)


def test_token_budget_tokens_saved_vs_raw() -> None:
    tracker = TokenBudgetTracker(max_tokens=1000)
    tracker.consume(20)
    tracker.add_raw(200)
    budget = tracker.to_token_budget()
    assert budget.tokens_saved_vs_raw == 180
    assert budget.estimated_tokens == 20
    assert budget.max_tokens == 1000


def test_token_budget_never_negative_savings() -> None:
    tracker = TokenBudgetTracker(max_tokens=1000)
    tracker.consume(100)
    tracker.add_raw(10)
    budget = tracker.to_token_budget()
    assert budget.tokens_saved_vs_raw == 0


# ---------------------------------------------------------------------------
# admission controller
# ---------------------------------------------------------------------------


def test_admission_admits_grounded_valid_summary() -> None:
    tracker = TokenBudgetTracker(max_tokens=500)
    ctrl = ContextAdmissionController(tracker)
    summary = _make_summary(facts=[_fact("file exists")])
    decision, reason = ctrl.evaluate(summary)
    assert decision == "admit"
    assert reason is None


def test_admission_omits_stale_summary() -> None:
    tracker = TokenBudgetTracker(max_tokens=500)
    ctrl = ContextAdmissionController(tracker)
    summary = _make_summary(facts=[_fact("old fact")], validity_status="stale")
    decision, reason = ctrl.evaluate(summary)
    assert decision == "omit"
    assert reason is not None and "stale" in reason


def test_admission_omits_contradicted_summary() -> None:
    tracker = TokenBudgetTracker(max_tokens=500)
    ctrl = ContextAdmissionController(tracker)
    summary = _make_summary(facts=[_fact("x")], validity_status="contradicted")
    decision, reason = ctrl.evaluate(summary)
    assert decision == "omit"
    assert reason is not None and "contradicted" in reason


def test_admission_omits_empty_summary() -> None:
    tracker = TokenBudgetTracker(max_tokens=500)
    ctrl = ContextAdmissionController(tracker)
    summary = _make_summary()
    decision, reason = ctrl.evaluate(summary)
    assert decision == "omit"
    assert reason == "no admissible content"


def test_admission_omits_duplicate_content() -> None:
    tracker = TokenBudgetTracker(max_tokens=500)
    ctrl = ContextAdmissionController(tracker)
    summary_a = _make_summary("sum-a", facts=[_fact("duplicate text")])
    summary_b = _make_summary("sum-b", facts=[_fact("duplicate text")])
    ctrl.evaluate(summary_a)
    decision, reason = ctrl.evaluate(summary_b)
    assert decision == "omit"
    assert reason == "duplicate content"


def test_admission_omits_when_budget_exceeded() -> None:
    tracker = TokenBudgetTracker(max_tokens=1)  # tiny budget
    ctrl = ContextAdmissionController(tracker)
    summary = _make_summary(facts=[_fact("a" * 100)])
    decision, reason = ctrl.evaluate(summary)
    assert decision == "omit"
    assert reason == "token budget exceeded"


def test_admission_decision_record_has_tokens_for_admitted() -> None:
    tracker = TokenBudgetTracker(max_tokens=500)
    ctrl = ContextAdmissionController(tracker)
    summary = _make_summary(facts=[_fact("present")])
    decision, reason = ctrl.evaluate(summary)
    dec = ctrl.make_decision(summary, decision, reason)
    assert dec.decision == "admit"
    assert dec.estimated_tokens is not None and dec.estimated_tokens > 0


def test_admission_decision_record_no_tokens_for_omitted() -> None:
    tracker = TokenBudgetTracker(max_tokens=500)
    ctrl = ContextAdmissionController(tracker)
    summary = _make_summary()
    decision, reason = ctrl.evaluate(summary)
    dec = ctrl.make_decision(summary, decision, reason)
    assert dec.decision == "omit"
    assert dec.estimated_tokens is None


# ---------------------------------------------------------------------------
# build_context_pack - acceptance criteria
# ---------------------------------------------------------------------------


def test_build_context_pack_summary_only_mode() -> None:
    summary = _make_summary(facts=[_fact("server lives in api/server.py")])
    pack, _ = build_context_pack(
        request_id="req-1",
        session_id="sess-1",
        repo_id="photon",
        summaries=[summary],
        budget=ContextPackBudget(),
    )
    assert pack.mode == "summary_only"
    assert len(pack.items) == 1
    assert "FACT:" in pack.items[0].text


def test_build_context_pack_returns_admission_decisions() -> None:
    summaries = [
        _make_summary("sum-a", facts=[_fact("fact a")]),
        _make_summary("sum-b"),  # empty; will be omitted
    ]
    pack, decisions = build_context_pack(
        request_id="req-2",
        session_id=None,
        repo_id=None,
        summaries=summaries,
        budget=ContextPackBudget(),
    )
    assert len(decisions) == 2
    assert decisions[0].decision == "admit"
    assert decisions[1].decision == "omit"


def test_build_context_pack_enforces_max_memory_tokens() -> None:
    big_text = "large safe context phrase " * 20  # ~130 tokens
    summaries = [
        _make_summary("sum-a", facts=[_fact(big_text, "ev-1")]),
        _make_summary("sum-b", facts=[_fact("small fact", "ev-2")]),
    ]
    pack, decisions = build_context_pack(
        request_id="req-3",
        session_id=None,
        repo_id=None,
        summaries=summaries,
        budget=ContextPackBudget(max_memory_tokens=101),  # room for ~first only
    )
    assert len(pack.items) == 1
    assert len(pack.omitted) == 1
    assert pack.omitted[0].reason == "token budget exceeded"


def test_build_context_pack_calculates_tokens_saved_vs_raw() -> None:
    tc = TokenCost(estimated_summary_tokens=10, estimated_raw_tokens=200, tokens_saved_vs_raw=190)
    summary = _make_summary(facts=[_fact("grounded")], token_cost=tc)
    pack, _ = build_context_pack(
        request_id="req-4",
        session_id=None,
        repo_id=None,
        summaries=[summary],
        budget=ContextPackBudget(),
    )
    assert pack.token_budget.tokens_saved_vs_raw is not None
    assert pack.token_budget.tokens_saved_vs_raw > 0


def test_build_context_pack_omits_stale_items() -> None:
    summaries = [
        _make_summary("sum-stale", facts=[_fact("stale info")], validity_status="stale"),
        _make_summary("sum-ok", facts=[_fact("fresh info")]),
    ]
    pack, _ = build_context_pack(
        request_id="req-5",
        session_id=None,
        repo_id=None,
        summaries=summaries,
        budget=ContextPackBudget(),
    )
    assert len(pack.items) == 1
    assert pack.items[0].id == "sum-ok"
    assert len(pack.omitted) == 1
    assert pack.omitted[0].id == "sum-stale"


def test_build_context_pack_omits_ungrounded_empty_summary() -> None:
    summary = _make_summary("sum-empty")
    pack, decisions = build_context_pack(
        request_id="req-6",
        session_id=None,
        repo_id=None,
        summaries=[summary],
        budget=ContextPackBudget(),
    )
    assert len(pack.items) == 0
    assert len(pack.omitted) == 1
    assert decisions[0].decision == "omit"


def test_build_context_pack_omits_duplicates() -> None:
    text = "exact same fact"
    summaries = [
        _make_summary("sum-a", facts=[_fact(text)]),
        _make_summary("sum-b", facts=[_fact(text)]),
    ]
    pack, _ = build_context_pack(
        request_id="req-7",
        session_id=None,
        repo_id=None,
        summaries=summaries,
        budget=ContextPackBudget(),
    )
    assert len(pack.items) == 1
    assert len(pack.omitted) == 1


def test_build_context_pack_empty_summaries_returns_valid_pack() -> None:
    pack, decisions = build_context_pack(
        request_id="req-8",
        session_id=None,
        repo_id=None,
        summaries=[],
        budget=ContextPackBudget(),
    )
    assert pack.mode == "summary_only"
    assert pack.items == []
    assert decisions == []
    assert pack.token_budget.estimated_tokens == 0


def test_build_context_pack_failed_attempt_and_avoid_admitted() -> None:
    summary = _make_summary(
        "sum-mixed",
        failed_attempts=[_failed("run tests")],
        avoid=[AvoidGuidance(action="grep everything", reason="too noisy", evidence_ids=[])],
    )
    pack, decisions = build_context_pack(
        request_id="req-9",
        session_id=None,
        repo_id=None,
        summaries=[summary],
        budget=ContextPackBudget(),
    )
    assert len(pack.items) == 1
    assert "FAILED:" in pack.items[0].text
    assert "AVOID:" in pack.items[0].text


# ---------------------------------------------------------------------------
# API integration - POST /v1/context/pack
# ---------------------------------------------------------------------------


def _pack_request(*, candidate_ids: list[str] | None = None, max_tokens: int = 800) -> dict:  # type: ignore[type-arg]
    return {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "req-api-1",
        "agent": {"name": "codex"},
        "repo": {"root": "/tmp", "name": "photon-test"},
        "task": {
            "user_request": "implement feature X",
            "mode": "act",
            "summary": "working on feature X",
        },
        "working_memory": {"touched_files": ["photon_action_memory/api/server.py"]},
        "recent_event_ids": [],
        "candidate_summary_ids": candidate_ids or [],
        "budget": {"max_memory_tokens": max_tokens, "max_evidence_chars": 1200},
    }


def test_context_pack_api_returns_summary_only_pack(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    with TestClient(app) as client:
        response = client.post("/v1/context/pack", json=_pack_request())

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"] == "req-api-1"
    assert payload["sidecar_status"] == "ok"
    assert payload["context_pack"]["mode"] == "summary_only"
    assert payload["admission_decisions"] == []


def test_context_pack_api_ok_when_unknown_summary_ids_given(tmp_path: Path) -> None:
    # Unknown IDs are silently skipped now that the summary store is always available.
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    with TestClient(app) as client:
        response = client.post("/v1/context/pack", json=_pack_request(candidate_ids=["sum-xyz"]))

    assert response.status_code == 200
    payload = response.json()
    assert payload["sidecar_status"] == "ok"
    assert payload["context_pack"]["warnings"] == []
    assert payload["context_pack"]["items"] == []


def test_context_pack_api_fail_open_on_internal_error(tmp_path: Path) -> None:
    """The route must return a valid response even when the pack builder raises."""
    from unittest.mock import patch

    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    with patch(
        "photon_action_memory.api.server.build_context_pack",
        side_effect=RuntimeError("simulated failure"),
    ):
        with TestClient(app) as client:
            response = client.post("/v1/context/pack", json=_pack_request())

    assert response.status_code == 200
    payload = response.json()
    assert payload["sidecar_status"] == "fail-open"
    assert payload["context_pack"]["warnings"][0]["kind"] == "pack_error"


def test_context_pack_api_token_budget_in_response(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    with TestClient(app) as client:
        response = client.post("/v1/context/pack", json=_pack_request(max_tokens=500))

    assert response.status_code == 200
    budget = response.json()["context_pack"]["token_budget"]
    assert budget["max_tokens"] == 500
    assert budget["estimated_tokens"] == 0


def test_context_pack_api_resolves_stored_summaries(tmp_path: Path) -> None:
    ss = SummaryStore(tmp_path / "summaries.sqlite")
    summary = _make_summary("sum-stored", facts=[_fact("stored fact about the repo")])
    ss.upsert(summary)
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"), summary_store=ss)
    with TestClient(app) as client:
        response = client.post(
            "/v1/context/pack",
            json=_pack_request(candidate_ids=["sum-stored"]),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sidecar_status"] == "ok"
    items = payload["context_pack"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == "sum-stored"
    assert "FACT:" in items[0]["text"]


def test_context_pack_api_auto_resolves_repo_summaries_without_candidate_ids(
    tmp_path: Path,
) -> None:
    ss = SummaryStore(tmp_path / "summaries.sqlite")
    summary = _make_summary(
        "sum-auto-repo",
        repo_id="photon-test",
        facts=[_fact("the live injection codename is heliograph")],
    )
    ss.upsert(summary)
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"), summary_store=ss)
    with TestClient(app) as client:
        response = client.post("/v1/context/pack", json=_pack_request())

    assert response.status_code == 200
    payload = response.json()
    items = payload["context_pack"]["items"]
    assert [item["id"] for item in items] == ["sum-auto-repo"]
    assert "heliograph" in items[0]["text"]
    assert payload["admission_decisions"][0]["decision"] == "admit"


def test_context_pack_api_auto_search_prefers_task_signature(tmp_path: Path) -> None:
    ss = SummaryStore(tmp_path / "summaries.sqlite")
    ss.upsert(
        _make_summary(
            "sum-repo-only",
            repo_id="photon-test",
            facts=[_fact("repo-wide memory")],
        )
    )
    ss.upsert(
        _make_summary(
            "sum-task",
            repo_id="photon-test",
            task_signature="live-codename-task",
            facts=[_fact("task-specific memory")],
        )
    )
    body = _pack_request()
    body["task"]["task_signature"] = "live-codename-task"
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"), summary_store=ss)
    with TestClient(app) as client:
        response = client.post("/v1/context/pack", json=body)

    assert response.status_code == 200
    items = response.json()["context_pack"]["items"]
    assert [item["id"] for item in items] == ["sum-task"]
    assert "task-specific memory" in items[0]["text"]


def test_context_pack_api_auto_resolves_repo_from_root_basename(tmp_path: Path) -> None:
    ss = SummaryStore(tmp_path / "summaries.sqlite")
    ss.upsert(
        _make_summary(
            "sum-root-name",
            repo_id="anvil-live-fixture",
            facts=[_fact("root basename lookup works")],
        )
    )
    body = _pack_request()
    body["repo"] = {"root": "/tmp/anvil-live-fixture"}
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"), summary_store=ss)
    with TestClient(app) as client:
        response = client.post("/v1/context/pack", json=body)

    assert response.status_code == 200
    payload = response.json()
    assert payload["context_pack"]["repo_id"] == "anvil-live-fixture"
    assert payload["context_pack"]["items"][0]["id"] == "sum-root-name"


def test_context_pack_api_auto_search_excludes_stale_and_omits_empty(
    tmp_path: Path,
) -> None:
    ss = SummaryStore(tmp_path / "summaries.sqlite")
    ss.upsert(
        _make_summary(
            "sum-valid",
            repo_id="photon-test",
            facts=[_fact("valid live memory")],
        )
    )
    ss.upsert(
        _make_summary(
            "sum-stale",
            repo_id="photon-test",
            facts=[_fact("stale live memory")],
            validity_status="stale",
        )
    )
    ss.upsert(_make_summary("sum-empty", repo_id="photon-test"))
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"), summary_store=ss)
    with TestClient(app) as client:
        response = client.post("/v1/context/pack", json=_pack_request())

    assert response.status_code == 200
    payload = response.json()["context_pack"]
    item_ids = {item["id"] for item in payload["items"]}
    omitted_ids = {item["id"] for item in payload["omitted"]}
    assert item_ids == {"sum-valid"}
    assert "sum-stale" not in item_ids
    assert omitted_ids == {"sum-empty"}


def test_context_pack_api_masks_prompt_visible_summary_secrets(tmp_path: Path) -> None:
    ss = SummaryStore(tmp_path / "summaries.sqlite")
    ss.upsert(
        _make_summary(
            "sum-secret",
            repo_id="photon-test",
            facts=[
                _fact(
                    "Use token=sk-liveinjectionsecret1234567890 from "
                    "/Users/example/private/project/.env"
                )
            ],
        )
    )
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"), summary_store=ss)
    with TestClient(app) as client:
        response = client.post("/v1/context/pack", json=_pack_request())

    assert response.status_code == 200
    item_text = response.json()["context_pack"]["items"][0]["text"]
    assert REDACTED_SECRET in item_text
    assert "sk-liveinjectionsecret1234567890" not in item_text
    assert "/Users/example" not in item_text
    assert "[ABS_PATH]/.env" in item_text


def test_context_pack_api_excludes_stale_stored_summaries(tmp_path: Path) -> None:
    ss = SummaryStore(tmp_path / "summaries.sqlite")
    stale = _make_summary("sum-stale", facts=[_fact("old fact")], validity_status="stale")
    fresh = _make_summary("sum-fresh", facts=[_fact("fresh fact")])
    ss.upsert(stale)
    ss.upsert(fresh)
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"), summary_store=ss)
    with TestClient(app) as client:
        response = client.post(
            "/v1/context/pack",
            json=_pack_request(candidate_ids=["sum-stale", "sum-fresh"]),
        )

    assert response.status_code == 200
    payload = response.json()
    items = payload["context_pack"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == "sum-fresh"


def test_upsert_summary_api_stores_and_retrieves(tmp_path: Path) -> None:
    ss = SummaryStore(tmp_path / "summaries.sqlite")
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"), summary_store=ss)
    upsert_payload = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "req-upsert-1",
        "summary": _make_summary("sum-api-upsert", facts=[_fact("upserted fact")]).model_dump(
            mode="json"
        ),
    }
    with TestClient(app) as client:
        resp = client.post("/v1/summary/upsert", json=upsert_payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["summary_id"] == "sum-api-upsert"
    assert data["status"] == "stored"
    assert ss.get("sum-api-upsert") is not None
