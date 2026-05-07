"""Tests for Anvil shadow → canary rollout policy (Issue #72).

Covers:
- is_canary_eligible() turn-count gate
- is_canary_eligible() raw-tool-token gate
- is_canary_eligible() fail-open rate gate
- build_rollout_metrics() generates correct metrics from Anvil eval fixtures
- rollback conditions verified via fixture
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from photon_action_memory.context.canary import (
    CanaryRolloutPolicy,
    is_canary_eligible,
)
from photon_action_memory.eval.metrics import (
    RolloutMetrics,
    build_rollout_metrics,
)

FIXTURES_V2 = Path(__file__).parent / "fixtures" / "v0.2"


def _load_rollout_fixture() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((FIXTURES_V2 / "rollout_metrics_fixture.json").read_text(encoding="utf-8")),
    )


# ---------------------------------------------------------------------------
# is_canary_eligible — unit tests
# ---------------------------------------------------------------------------


def test_is_canary_eligible_passes_all_gates() -> None:
    eligible, reason = is_canary_eligible(10, 0)
    assert eligible is True
    assert reason == "eligible for canary"


def test_is_canary_eligible_too_few_turns() -> None:
    policy = CanaryRolloutPolicy(min_turns_for_canary=10)
    eligible, reason = is_canary_eligible(5, 0, policy=policy)
    assert eligible is False
    assert "turn count 5 < min 10" in reason


def test_is_canary_eligible_minimum_turns_boundary() -> None:
    policy = CanaryRolloutPolicy(min_turns_for_canary=10)
    eligible_at_min, _ = is_canary_eligible(10, 0, policy=policy)
    eligible_below, _ = is_canary_eligible(9, 0, policy=policy)
    assert eligible_at_min is True
    assert eligible_below is False


def test_is_canary_eligible_raw_tool_tokens_nonzero() -> None:
    eligible, reason = is_canary_eligible(15, 124)
    assert eligible is False
    assert "raw_tool_tokens_in_prompt=124 must be 0" in reason


def test_is_canary_eligible_raw_tool_tokens_zero_passes() -> None:
    eligible, _ = is_canary_eligible(15, 0)
    assert eligible is True


def test_is_canary_eligible_high_fail_open_rate() -> None:
    policy = CanaryRolloutPolicy(min_turns_for_canary=5, max_fail_open_rate=0.05)
    eligible, reason = is_canary_eligible(10, 0, fail_open_incident_rate=0.3, policy=policy)
    assert eligible is False
    assert "fail_open_incident_rate=0.300" in reason


def test_is_canary_eligible_fail_open_at_threshold_passes() -> None:
    policy = CanaryRolloutPolicy(max_fail_open_rate=0.05)
    eligible, _ = is_canary_eligible(10, 0, fail_open_incident_rate=0.05, policy=policy)
    assert eligible is True


def test_is_canary_eligible_turn_check_before_raw_token_check() -> None:
    # Turn count gate is checked first; raw-token gate is secondary.
    policy = CanaryRolloutPolicy(min_turns_for_canary=10)
    eligible, reason = is_canary_eligible(3, 200, policy=policy)
    assert eligible is False
    assert "turn count" in reason


# ---------------------------------------------------------------------------
# build_rollout_metrics — fixture-driven integration tests
# ---------------------------------------------------------------------------


def test_rollout_metrics_canary_ready_fixture() -> None:
    fixture = _load_rollout_fixture()
    scenario = fixture["scenarios"]["canary_ready"]
    metrics = build_rollout_metrics(
        scenario["eval_records"],
        raw_tool_tokens_in_prompt=scenario["raw_tool_tokens_in_prompt"],
        min_turns_for_canary=10,
    )
    assert isinstance(metrics, RolloutMetrics)
    assert metrics.total_turns == 10
    assert metrics.raw_tool_tokens_in_prompt == 0
    assert metrics.canary_eligible is True
    assert metrics.ineligible_reason is None
    assert metrics.rollback_triggered is False
    assert metrics.rollback_reason is None


def test_rollout_metrics_too_few_turns_ineligible() -> None:
    fixture = _load_rollout_fixture()
    scenario = fixture["scenarios"]["too_few_turns"]
    metrics = build_rollout_metrics(
        scenario["eval_records"],
        raw_tool_tokens_in_prompt=scenario["raw_tool_tokens_in_prompt"],
        min_turns_for_canary=10,
    )
    assert metrics.total_turns == 5
    assert metrics.canary_eligible is False
    assert metrics.ineligible_reason is not None
    assert "turn count 5 < min 10" in metrics.ineligible_reason
    assert metrics.rollback_triggered is False


def test_rollout_metrics_raw_tool_leak_triggers_rollback() -> None:
    fixture = _load_rollout_fixture()
    scenario = fixture["scenarios"]["raw_tool_leak"]
    metrics = build_rollout_metrics(
        scenario["eval_records"],
        raw_tool_tokens_in_prompt=scenario["raw_tool_tokens_in_prompt"],
        min_turns_for_canary=10,
    )
    assert metrics.total_turns == 10
    assert metrics.raw_tool_tokens_in_prompt == 124
    assert metrics.rollback_triggered is True
    assert metrics.rollback_reason is not None
    assert "raw_tool_tokens_in_prompt=124" in metrics.rollback_reason
    assert metrics.canary_eligible is False


def test_rollout_metrics_high_fail_open_triggers_rollback() -> None:
    fixture = _load_rollout_fixture()
    scenario = fixture["scenarios"]["high_fail_open"]
    metrics = build_rollout_metrics(
        scenario["eval_records"],
        raw_tool_tokens_in_prompt=scenario["raw_tool_tokens_in_prompt"],
        min_turns_for_canary=10,
        max_fail_open_rate=0.05,
    )
    assert metrics.total_turns == 10
    assert metrics.fail_open_incident_rate == pytest.approx(0.3)
    assert metrics.rollback_triggered is True
    assert metrics.rollback_reason is not None
    assert "fail_open_incident_rate" in metrics.rollback_reason
    assert metrics.canary_eligible is False


def test_rollout_metrics_schema_version() -> None:
    metrics = build_rollout_metrics(
        [
            {
                "context_pack_request_id": "x",
                "adoption_status": "adopted",
                "items_adopted_count": 1,
                "items_ignored_count": 0,
            }
        ]
        * 10,
        raw_tool_tokens_in_prompt=0,
    )
    assert metrics.schema_version == "rollout-metrics.v1"


def test_rollout_metrics_empty_records() -> None:
    metrics = build_rollout_metrics([], raw_tool_tokens_in_prompt=0, min_turns_for_canary=10)
    assert metrics.total_turns == 0
    assert metrics.canary_eligible is False
    assert metrics.ineligible_reason is not None
    assert "turn count 0" in metrics.ineligible_reason
