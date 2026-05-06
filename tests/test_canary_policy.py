"""Tests for Context Firewall canary-mode admission policy."""

from __future__ import annotations

import json
from pathlib import Path

from photon_action_memory.api.schema_v2 import ContextPack, EvaluateRequest
from photon_action_memory.context.canary import (
    CANARY_ALLOWED_CLASSES,
    CANARY_DENIED_CLASSES,
    CANARY_MODE_CONFIG,
    CanaryCandidate,
    CanaryModeConfig,
    evaluate_canary_candidate,
    evaluate_canary_candidates,
)
from photon_action_memory.eval.context_pack_log import aggregate_context_pack_eval


def test_canary_allows_only_low_risk_classes() -> None:
    decisions = evaluate_canary_candidates(
        [
            {"candidate_id": f"allowed-{kind}", "action_class": kind}
            for kind in sorted(CANARY_ALLOWED_CLASSES)
        ]
    )

    assert {decision.decision for decision in decisions} == {"admit"}
    assert all("low-risk" in str(decision.reason) for decision in decisions)


def test_canary_denies_risky_classes() -> None:
    decisions = evaluate_canary_candidates(
        [
            {"candidate_id": f"denied-{kind}", "action_class": kind}
            for kind in sorted(CANARY_DENIED_CLASSES)
        ]
    )

    assert {decision.decision for decision in decisions} == {"deny"}
    assert all("canary denied" in str(decision.reason) for decision in decisions)


def test_canary_defer_unknown_class_to_preserve_fail_open() -> None:
    decision = evaluate_canary_candidate(
        CanaryCandidate(candidate_id="unknown-1", action_class="unknown_experimental_tool")
    )

    assert decision.decision == "defer"
    assert decision.reason == "canary fail-open: unknown action class: unknown_experimental_tool"


def test_canary_defer_invalid_candidate_to_preserve_fail_open() -> None:
    decision = evaluate_canary_candidate({"action_class": "read_candidate"})

    assert decision.decision == "defer"
    assert decision.item_id == "unknown"
    assert "invalid candidate" in str(decision.reason)


def test_canary_disabled_defer_without_denial() -> None:
    decision = evaluate_canary_candidate(
        CanaryCandidate(candidate_id="read-1", action_class="read_candidate"),
        config=CanaryModeConfig(enabled=False),
    )

    assert decision.decision == "defer"
    assert decision.reason == "canary policy disabled"


def test_canary_decision_records_policy_metadata() -> None:
    decision = evaluate_canary_candidate(
        CanaryCandidate(
            candidate_id="summary-1",
            action_class="summary_only_memory",
            item_kind="action_summary",
            estimated_tokens=42,
        )
    )

    assert decision.policy is not None
    assert decision.policy.raw_evidence_policy == "raw_tool_log_default_deny"
    assert decision.policy.detail_level == CANARY_MODE_CONFIG.policy_name
    assert decision.estimated_tokens == 42


def test_canary_context_pack_fixture_is_summary_only_and_low_risk() -> None:
    fixture = _load_fixture("canary_context_pack.json")
    pack = ContextPack.model_validate(fixture)

    assert pack.mode == "summary_only"
    assert [item.kind for item in pack.items] == ["action_summary", "warning", "warning"]
    assert {omitted.reason for omitted in pack.omitted} == {
        "canary denied action class: destructive_shell_command",
        "canary denied action class: edit_auto_approval",
        "raw tool log default deny policy: kind 'stdout' is always denied",
    }


def test_canary_shadow_mode_evaluate_fixture_is_aggregate_safe() -> None:
    fixture = _load_fixture("canary_evaluate_shadow_mode.json")
    request = EvaluateRequest.model_validate(fixture)
    assert request.context_pack_event is not None

    report = aggregate_context_pack_eval([request.context_pack_event.model_dump()])

    assert report.total_turns == 1
    assert report.adopted_count == 0
    assert report.ignored_count == 0
    assert report.partial_count == 1
    assert report.task_success_rate == 1.0


def _load_fixture(name: str) -> object:
    path = Path("tests/fixtures/v0.2") / name
    return json.loads(path.read_text(encoding="utf-8"))
