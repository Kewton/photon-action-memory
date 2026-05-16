"""Issue #119 — answer-leak quality-gate regression tests.

AL-01: S1-02 fixture trips ``output_key_enumeration`` / ``direct_print_answer``.
AL-02: legitimate "summarize.py reads JSON files" text stays clean.
AL-03: PHOTON_QUALITY_GATE_MODE strict/warn/observe paths through
       ``/v1/summary/upsert`` behave per the contract.
AL-04: semantic-similarity layer B is not implemented in #119 — the slot
       is reserved with a skip so the follow-up can drop a real check in.
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
    NextHint,
)
from photon_action_memory.api.server import create_app
from photon_action_memory.governance.answer_leak import (
    ANSWER_LEAK_PATTERNS,
    detect_answer_leak,
    evaluate_summary_quality,
)
from photon_action_memory.memory.store import SQLiteEventStore
from photon_action_memory.memory.summary_store import SummaryStore

FIXTURES_SHARED = Path(__file__).parent / "fixtures" / "shared"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client(tmp_path: Path) -> TestClient:
    event_store = SQLiteEventStore(tmp_path / "events.sqlite")
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    return TestClient(create_app(event_store, summary_store))


def _upsert_body(summary: ActionSummary, request_id: str = "test-upsert") -> dict[str, object]:
    return {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": request_id,
        "summary": summary.model_dump(mode="json"),
    }


def _make_summary(facts_text: list[str], summary_id: str = "test-sum") -> ActionSummary:
    return ActionSummary(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        summary_id=summary_id,
        repo_id="test-repo",
        task_signature="test-task",
        facts=[Fact(text=text, evidence_ids=["ev-1"]) for text in facts_text],
        next_hints=[NextHint(kind="action", reason="run python3 summarize.py")],
    )


# ---------------------------------------------------------------------------
# Pattern SSOT
# ---------------------------------------------------------------------------


def test_answer_leak_patterns_meet_minimum_count() -> None:
    """Acceptance criteria require 6+ patterns in the SSOT."""
    assert len(ANSWER_LEAK_PATTERNS) >= 6
    names = {name for name, _ in ANSWER_LEAK_PATTERNS}
    assert "output_literal_json" in names
    assert "output_key_enumeration" in names


# ---------------------------------------------------------------------------
# AL-01: S1-02 positive case
# ---------------------------------------------------------------------------


def test_al01_positive_s1_02_fixture_detects_leak() -> None:
    raw = json.loads(
        (FIXTURES_SHARED / "anvil_eval_s1_02_action_summary.json").read_text(encoding="utf-8")
    )
    summary = ActionSummary.model_validate(raw)
    report = evaluate_summary_quality(summary)

    assert report.status == "warned"
    pattern_names = {match.pattern for _path, match in report.matches}
    # The fact text "prints a JSON object with keys alpha, beta, and total"
    # is the canonical S1-02 answer-key leak — at least one of the two
    # patterns that target this shape must fire.
    assert pattern_names & {"output_key_enumeration", "direct_print_answer"}, (
        f"expected output_key_enumeration or direct_print_answer in {pattern_names}"
    )
    assert any("facts[0].text" in warning for warning in report.warnings)


# ---------------------------------------------------------------------------
# AL-02: false-positive prevention
# ---------------------------------------------------------------------------


def test_al02_false_positive_prevention_legitimate_fact_stays_clean() -> None:
    summary = _make_summary(
        [
            "summarize.py reads JSON files and validates them against a schema.",
            "Pytest fixtures live under tests/fixtures/ and load JSON via helpers.",
        ]
    )
    report = evaluate_summary_quality(summary)
    assert report.status == "clean"
    assert report.warnings == ()
    assert report.matches == ()


def test_detect_answer_leak_returns_one_match_per_pattern() -> None:
    """If the same pattern would fire twice in a string, we keep only the
    first hit so the report stays focused on which *kind* of leak fired."""
    text = (
        "the answer is 42. the result is 99. the output is something else."
        " stdout will be 'foo'. stdout contains 'bar'."
    )
    matches = detect_answer_leak(text)
    pattern_names = [m.pattern for m in matches]
    assert pattern_names.count("answer_assertion") == 1
    assert pattern_names.count("stdout_forecast") == 1


# ---------------------------------------------------------------------------
# AL-03: strict / warn / observe behaviour through the route
# ---------------------------------------------------------------------------


_LEAKY_SUMMARY = _make_summary(
    [
        "summarize.py prints a JSON object with keys alpha, beta, and total.",
    ],
    summary_id="leaky-sum-001",
)


def test_al03_strict_mode_rejects_leaky_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PHOTON_QUALITY_GATE_MODE", "strict")
    with _client(tmp_path) as client:
        resp = client.post("/v1/summary/upsert", json=_upsert_body(_LEAKY_SUMMARY))
    assert resp.status_code == 422
    body = resp.json()
    detail = body["detail"]
    assert detail["error"] == "answer_leak_detected"
    assert detail["summary_id"] == "leaky-sum-001"
    assert detail["quality_warnings"], "strict mode must surface the leak warnings"


def test_al03_warn_mode_annotates_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PHOTON_QUALITY_GATE_MODE", "warn")
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    event_store = SQLiteEventStore(tmp_path / "events.sqlite")
    with TestClient(create_app(event_store, summary_store)) as client:
        resp = client.post("/v1/summary/upsert", json=_upsert_body(_LEAKY_SUMMARY))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "stored_with_warnings"
    persisted = summary_store.get("leaky-sum-001")
    assert persisted is not None
    assert persisted.quality_check_status == "warned"
    assert persisted.quality_warnings, "warn mode must persist the gate warnings"
    summary_store.close()


def test_al03_observe_mode_passes_through(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHOTON_QUALITY_GATE_MODE", "observe")
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    event_store = SQLiteEventStore(tmp_path / "events.sqlite")
    with TestClient(create_app(event_store, summary_store)) as client:
        resp = client.post("/v1/summary/upsert", json=_upsert_body(_LEAKY_SUMMARY))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "stored"
    persisted = summary_store.get("leaky-sum-001")
    assert persisted is not None
    # observe leaves the seed unchanged so existing-seed re-upsert doesn't
    # silently relabel; the warning lives in the operator log only.
    assert persisted.quality_check_status == "unchecked"
    assert persisted.quality_warnings == []
    summary_store.close()


def test_al03_clean_summary_stored_with_clean_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PHOTON_QUALITY_GATE_MODE", "warn")
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    event_store = SQLiteEventStore(tmp_path / "events.sqlite")
    clean = _make_summary(
        ["summarize.py reads JSON files and validates them."],
        summary_id="clean-sum-001",
    )
    with TestClient(create_app(event_store, summary_store)) as client:
        resp = client.post("/v1/summary/upsert", json=_upsert_body(clean))
    assert resp.status_code == 200
    assert resp.json()["status"] == "stored"
    persisted = summary_store.get("clean-sum-001")
    assert persisted is not None
    assert persisted.quality_check_status == "clean"
    assert persisted.quality_warnings == []
    summary_store.close()


# ---------------------------------------------------------------------------
# AL-04: semantic similarity (layer B) — reserved slot
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "Issue #119 ships layer A (regex SSOT) only; the semantic-similarity"
        " layer B is a follow-up. This slot is reserved so the follow-up"
        " test name is stable."
    )
)
def test_al04_semantic_similarity_layer_b() -> None:  # pragma: no cover - placeholder
    raise NotImplementedError
