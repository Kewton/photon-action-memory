"""Focused schema tests for Action Context Firewall v0.2 models (Issue #32)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionChunk,
    ActionSummary,
    ContextAdmissionDecision,
    ContextPack,
    ContextPackRequest,
    ContextPackResponse,
    EvaluateRequest,
    EvidenceExpandRequest,
    EvidenceExpandResponse,
    EvidenceRef,
    SummarizePolicy,
    SummarizeRequest,
    SummarizeResponse,
    SummaryValidateRequest,
    SummaryValidateResponse,
    SummaryValidationResult,
)

SCHEMA_V2 = DEFAULT_SCHEMA_VERSION_V2
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "v0.2"
SHARED_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "shared"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def minimal_token_budget() -> dict[str, object]:
    return {"max_tokens": 800, "estimated_tokens": 0}


def minimal_context_pack() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_V2,
        "request_id": "req-001",
        "mode": "summary_only",
        "token_budget": minimal_token_budget(),
    }


# ---------------------------------------------------------------------------
# ActionChunk
# ---------------------------------------------------------------------------


class TestActionChunk:
    def test_minimal_round_trip(self) -> None:
        chunk = ActionChunk.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "chunk_id": "chunk_001",
                "session_id": "sess_001",
                "kind": "repo_search",
                "summary": "Searched SessionStore.",
            }
        )
        rt = ActionChunk.model_validate_json(chunk.model_dump_json())
        assert rt.schema_version == SCHEMA_V2
        assert rt.chunk_id == "chunk_001"
        assert rt.outcome == "unknown"
        assert rt.event_ids == []

    def test_full_payload(self) -> None:
        chunk = ActionChunk.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "chunk_id": "chunk_017",
                "session_id": "sess_001",
                "turn_id": "turn_006",
                "repo_id": "repo_001",
                "commit": "abc123",
                "kind": "repo_search",
                "event_ids": ["evt_041", "evt_042"],
                "started_at": "2026-04-30T10:00:00Z",
                "ended_at": "2026-04-30T10:02:00Z",
                "summary": "Found primary implementation.",
                "outcome": "useful",
                "risk": "low",
                "redaction_status": "sanitized",
            }
        )
        assert chunk.outcome == "useful"
        assert chunk.event_ids == ["evt_041", "evt_042"]
        assert chunk.risk == "low"

    def test_schema_version_required(self) -> None:
        with pytest.raises(ValidationError):
            ActionChunk.model_validate(
                {
                    "chunk_id": "chunk_001",
                    "session_id": "sess_001",
                    "kind": "repo_search",
                    "summary": "Missing version.",
                }
            )

    def test_unknown_fields_preserved(self) -> None:
        chunk = ActionChunk.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "chunk_id": "chunk_001",
                "session_id": "sess_001",
                "kind": "other",
                "summary": "test",
                "custom_tag": "experiment_42",
            }
        )
        assert chunk.model_dump()["custom_tag"] == "experiment_42"

    def test_missing_required_summary_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ActionChunk.model_validate(
                {
                    "schema_version": SCHEMA_V2,
                    "chunk_id": "chunk_001",
                    "session_id": "sess_001",
                    "kind": "repo_search",
                }
            )
        assert "summary" in str(exc_info.value)


# ---------------------------------------------------------------------------
# EvidenceRef
# ---------------------------------------------------------------------------


class TestEvidenceRef:
    def test_minimal_round_trip(self) -> None:
        ref = EvidenceRef.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "evidence_id": "evt_052",
                "kind": "test_output",
                "summary": "cargo test failed.",
            }
        )
        rt = EvidenceRef.model_validate_json(ref.model_dump_json())
        assert rt.evidence_id == "evt_052"
        assert rt.expand_policy == "on_demand_only"
        assert rt.staleness.status == "unknown"

    def test_full_payload_with_locator(self) -> None:
        ref = EvidenceRef.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "evidence_id": "evt_052",
                "source_event_id": "evt_052",
                "source_chunk_id": "chunk_018",
                "kind": "test_output",
                "summary": "cargo test session_persistence failed.",
                "locator": {
                    "file": "tests/session_persistence.rs",
                    "line_start": 42,
                    "line_end": 57,
                    "command": "cargo test session_persistence",
                },
                "redaction_status": "sanitized",
                "expand_policy": "on_demand_only",
                "max_expand_chars": 1200,
                "staleness": {"status": "valid"},
            }
        )
        assert ref.locator is not None
        assert ref.locator.line_start == 42
        assert ref.staleness.status == "valid"

    def test_schema_version_required(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceRef.model_validate(
                {"evidence_id": "evt_001", "kind": "file_read", "summary": "read result"}
            )

    def test_locator_is_optional(self) -> None:
        ref = EvidenceRef.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "evidence_id": "evt_001",
                "kind": "summary",
                "summary": "no locator needed",
            }
        )
        assert ref.locator is None

    def test_unknown_fields_preserved(self) -> None:
        ref = EvidenceRef.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "evidence_id": "evt_001",
                "kind": "diff",
                "summary": "diff result",
                "internal_score": 0.87,
            }
        )
        assert ref.model_dump()["internal_score"] == pytest.approx(0.87)


# ---------------------------------------------------------------------------
# ActionSummary — separate fields
# ---------------------------------------------------------------------------


class TestActionSummary:
    def _base(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_V2,
            "summary_id": "sum_001",
        }

    def test_minimal_round_trip(self) -> None:
        summary = ActionSummary.model_validate(self._base())
        rt = ActionSummary.model_validate_json(summary.model_dump_json())
        assert rt.summary_id == "sum_001"
        assert rt.facts == []
        assert rt.hypotheses == []
        assert rt.failed_attempts == []
        assert rt.avoid == []

    def test_facts_hypotheses_failed_attempts_avoid_are_separate(self) -> None:
        summary = ActionSummary.model_validate(
            {
                **self._base(),
                "facts": [
                    {
                        "text": "SessionStore is in store.rs.",
                        "evidence_ids": ["evt_041"],
                        "confidence": 0.95,
                    }
                ],
                "hypotheses": [
                    {
                        "text": "serde path may be involved.",
                        "evidence_ids": ["evt_052"],
                        "confidence": 0.62,
                        "status": "open",
                    }
                ],
                "failed_attempts": [
                    {
                        "action": "cargo test without changes",
                        "outcome": "same failure",
                        "evidence_ids": ["evt_052"],
                        "retry_policy": "avoid_until_files_changed",
                    }
                ],
                "avoid": [
                    {
                        "action": "repo-wide grep for SessionStore",
                        "reason": "already done",
                        "evidence_ids": ["evt_041"],
                    }
                ],
            }
        )
        assert len(summary.facts) == 1
        assert summary.facts[0].confidence == pytest.approx(0.95)
        assert len(summary.hypotheses) == 1
        assert summary.hypotheses[0].status == "open"
        assert len(summary.failed_attempts) == 1
        assert summary.failed_attempts[0].retry_policy == "avoid_until_files_changed"
        assert len(summary.avoid) == 1
        assert summary.avoid[0].reason == "already done"

    def test_actions_done_and_next_hints(self) -> None:
        summary = ActionSummary.model_validate(
            {
                **self._base(),
                "actions_done": [
                    {
                        "kind": "search",
                        "target": "SessionStore",
                        "outcome": "found",
                        "status": "useful",
                        "evidence_ids": ["evt_041"],
                    }
                ],
                "next_hints": [
                    {
                        "kind": "read",
                        "target": "src/session/store.rs",
                        "reason": "primary impl",
                        "confidence": 0.78,
                    }
                ],
            }
        )
        assert summary.actions_done[0].kind == "search"
        assert summary.next_hints[0].confidence == pytest.approx(0.78)

    def test_token_cost(self) -> None:
        summary = ActionSummary.model_validate(
            {
                **self._base(),
                "token_cost": {
                    "estimated_summary_tokens": 240,
                    "estimated_raw_tokens": 5200,
                    "tokens_saved_vs_raw": 4960,
                },
            }
        )
        assert summary.token_cost is not None
        assert summary.token_cost.tokens_saved_vs_raw == 4960

    def test_validity_defaults_to_valid(self) -> None:
        summary = ActionSummary.model_validate(self._base())
        assert summary.validity.status == "valid"

    def test_schema_version_required(self) -> None:
        with pytest.raises(ValidationError):
            ActionSummary.model_validate({"summary_id": "sum_001"})

    def test_unknown_fields_preserved(self) -> None:
        summary = ActionSummary.model_validate({**self._base(), "shadow_score": 0.9})
        assert summary.model_dump()["shadow_score"] == pytest.approx(0.9)

    def test_missing_summary_id_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ActionSummary.model_validate({"schema_version": SCHEMA_V2})
        assert "summary_id" in str(exc_info.value)

    def test_full_round_trip(self) -> None:
        payload: dict[str, object] = {
            "schema_version": SCHEMA_V2,
            "summary_id": "sum_001",
            "session_id": "sess_001",
            "repo_id": "repo_001",
            "commit": "abc123",
            "task_signature": "fix-session-persistence-test",
            "summary_level": "turn",
            "source_chunk_ids": ["chunk_017", "chunk_018"],
            "actions_done": [
                {
                    "kind": "search",
                    "target": "SessionStore",
                    "outcome": "found",
                    "status": "useful",
                    "evidence_ids": ["evt_041"],
                },
                {
                    "kind": "test",
                    "command": "cargo test session_persistence",
                    "outcome": "failed",
                    "status": "unresolved",
                    "evidence_ids": ["evt_052"],
                },
            ],
            "facts": [
                {
                    "text": "SessionStore in store.rs",
                    "evidence_ids": ["evt_041"],
                    "confidence": 0.95,
                }
            ],
            "hypotheses": [
                {
                    "text": "serde path related",
                    "evidence_ids": ["evt_052"],
                    "confidence": 0.62,
                    "status": "open",
                }
            ],
            "failed_attempts": [
                {
                    "action": "rerun cargo test without changes",
                    "outcome": "same failure",
                    "evidence_ids": ["evt_052"],
                    "retry_policy": "avoid_until_files_changed",
                }
            ],
            "avoid": [
                {
                    "action": "repo-wide grep for SessionStore",
                    "reason": "already performed",
                    "valid_until": "files_changed",
                    "evidence_ids": ["evt_041"],
                }
            ],
            "next_hints": [
                {
                    "kind": "read",
                    "target": "src/session/store.rs",
                    "reason": "primary impl",
                    "confidence": 0.78,
                }
            ],
            "token_cost": {
                "estimated_summary_tokens": 240,
                "estimated_raw_tokens": 5200,
                "tokens_saved_vs_raw": 4960,
            },
            "validity": {"status": "valid"},
        }
        summary = ActionSummary.model_validate(payload)
        rt = ActionSummary.model_validate_json(summary.model_dump_json())
        assert rt.summary_id == "sum_001"
        assert len(rt.facts) == 1
        assert len(rt.hypotheses) == 1
        assert len(rt.failed_attempts) == 1
        assert len(rt.avoid) == 1


# ---------------------------------------------------------------------------
# ContextAdmissionDecision
# ---------------------------------------------------------------------------


class TestContextAdmissionDecision:
    def test_minimal_round_trip(self) -> None:
        decision = ContextAdmissionDecision.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "decision_id": "adm_001",
                "item_id": "sum_001",
                "item_kind": "action_summary",
                "decision": "admit",
            }
        )
        rt = ContextAdmissionDecision.model_validate_json(decision.model_dump_json())
        assert rt.decision == "admit"
        assert rt.policy is None

    def test_with_policy(self) -> None:
        decision = ContextAdmissionDecision.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "decision_id": "adm_002",
                "item_id": "evt_052_raw",
                "item_kind": "raw_event",
                "decision": "deny",
                "reason": "raw output denied by policy",
                "risk": "high",
                "estimated_tokens": 3200,
                "policy": {
                    "raw_evidence_policy": "deny_by_default",
                    "detail_level": "summary_only",
                },
            }
        )
        assert decision.decision == "deny"
        assert decision.policy is not None
        assert decision.policy.raw_evidence_policy == "deny_by_default"

    def test_schema_version_required(self) -> None:
        with pytest.raises(ValidationError):
            ContextAdmissionDecision.model_validate(
                {
                    "decision_id": "adm_001",
                    "item_id": "sum_001",
                    "item_kind": "action_summary",
                    "decision": "admit",
                }
            )

    def test_missing_decision_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ContextAdmissionDecision.model_validate(
                {
                    "schema_version": SCHEMA_V2,
                    "decision_id": "adm_001",
                    "item_id": "sum_001",
                    "item_kind": "action_summary",
                }
            )
        assert "decision" in str(exc_info.value)


# ---------------------------------------------------------------------------
# ContextPack
# ---------------------------------------------------------------------------


class TestContextPack:
    def test_minimal_round_trip(self) -> None:
        pack = ContextPack.model_validate(minimal_context_pack())
        rt = ContextPack.model_validate_json(pack.model_dump_json())
        assert rt.schema_version == SCHEMA_V2
        assert rt.mode == "summary_only"
        assert rt.items == []
        assert rt.omitted == []
        assert rt.warnings == []

    def test_full_payload(self) -> None:
        pack = ContextPack.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "request_id": "turn_123",
                "session_id": "sess_001",
                "repo_id": "repo_001",
                "mode": "summary_only",
                "items": [
                    {
                        "kind": "action_summary",
                        "id": "sum_001",
                        "text": "Searched SessionStore; found in store.rs.",
                        "evidence_ids": ["evt_041"],
                        "admission_reason": "useful_recent_task_state",
                    }
                ],
                "omitted": [
                    {
                        "kind": "raw_tool_output",
                        "id": "evt_052_raw",
                        "reason": "raw output exceeds budget",
                    }
                ],
                "warnings": [
                    {
                        "kind": "repeat_failure",
                        "message": "Previous test command failed; do not retry without changes.",
                    }
                ],
                "token_budget": {
                    "max_tokens": 800,
                    "estimated_tokens": 260,
                    "tokens_saved_vs_raw": 5200,
                },
            }
        )
        assert pack.items[0].kind == "action_summary"
        assert pack.omitted[0].reason == "raw output exceeds budget"
        assert pack.warnings[0].kind == "repeat_failure"
        assert pack.token_budget.tokens_saved_vs_raw == 5200

    def test_schema_version_required(self) -> None:
        with pytest.raises(ValidationError):
            ContextPack.model_validate(
                {
                    "request_id": "req-001",
                    "mode": "summary_only",
                    "token_budget": minimal_token_budget(),
                }
            )

    def test_token_budget_required(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ContextPack.model_validate(
                {
                    "schema_version": SCHEMA_V2,
                    "request_id": "req-001",
                    "mode": "summary_only",
                }
            )
        assert "token_budget" in str(exc_info.value)

    def test_unknown_fields_preserved(self) -> None:
        pack = ContextPack.model_validate({**minimal_context_pack(), "canary_mode": True})
        assert pack.model_dump()["canary_mode"] is True


# ---------------------------------------------------------------------------
# SummaryValidationResult
# ---------------------------------------------------------------------------


class TestSummaryValidationResult:
    def test_minimal(self) -> None:
        result = SummaryValidationResult.model_validate(
            {"summary_id": "sum_001", "status": "valid"}
        )
        assert result.issues == []
        assert result.score is None

    def test_with_issues(self) -> None:
        result = SummaryValidationResult.model_validate(
            {
                "summary_id": "sum_001",
                "status": "partial",
                "score": 0.72,
                "issues": [
                    {"kind": "missing_evidence", "message": "Fact at index 1 has no evidence_id."}
                ],
                "checked_at": "2026-04-30T10:05:00Z",
            }
        )
        assert result.score == pytest.approx(0.72)
        assert result.issues[0].kind == "missing_evidence"

    def test_unknown_fields_preserved(self) -> None:
        result = SummaryValidationResult.model_validate(
            {"summary_id": "sum_001", "status": "valid", "validator_version": "0.2.1"}
        )
        assert result.model_dump()["validator_version"] == "0.2.1"


# ---------------------------------------------------------------------------
# ContextPackRequest / ContextPackResponse
# ---------------------------------------------------------------------------


class TestContextPackRequest:
    def test_round_trip(self) -> None:
        request = ContextPackRequest.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "request_id": "turn_123",
                "agent": {"name": "anvil"},
                "repo": {"root": "/repo"},
                "task": {"user_request": "Fix test", "mode": "act"},
                "working_memory": {},
                "recent_event_ids": ["evt_041"],
                "candidate_summary_ids": ["sum_001"],
            }
        )
        rt = ContextPackRequest.model_validate_json(request.model_dump_json())
        assert rt.request_id == "turn_123"
        assert rt.budget.max_memory_tokens == 800
        assert rt.recent_event_ids == ["evt_041"]

    def test_schema_version_required(self) -> None:
        with pytest.raises(ValidationError):
            ContextPackRequest.model_validate(
                {
                    "request_id": "turn_123",
                    "agent": {"name": "anvil"},
                    "repo": {"root": "/repo"},
                    "task": {"user_request": "Fix test", "mode": "act"},
                    "working_memory": {},
                }
            )


class TestContextPackResponse:
    def test_round_trip(self) -> None:
        response = ContextPackResponse.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "request_id": "turn_123",
                "model_version": "photon-action-memory-v0.2.0",
                "sidecar_status": "ok",
                "context_pack": minimal_context_pack(),
            }
        )
        rt = ContextPackResponse.model_validate_json(response.model_dump_json())
        assert rt.sidecar_status == "ok"
        assert rt.admission_decisions == []


# ---------------------------------------------------------------------------
# EvidenceExpandRequest / EvidenceExpandResponse
# ---------------------------------------------------------------------------


class TestEvidenceExpand:
    def test_request_round_trip(self) -> None:
        request = EvidenceExpandRequest.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "request_id": "expand_001",
                "evidence_ids": ["evt_052"],
                "reason": "Need exact failure message.",
            }
        )
        rt = EvidenceExpandRequest.model_validate_json(request.model_dump_json())
        assert rt.evidence_ids == ["evt_052"]
        assert rt.policy.allow_raw_full_output is False
        assert rt.policy.allow_selected_snippet is True

    def test_response_round_trip(self) -> None:
        response = EvidenceExpandResponse.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "request_id": "expand_001",
                "expanded": [
                    {
                        "evidence_id": "evt_052",
                        "kind": "test_output",
                        "summary": "cargo test failed",
                        "snippet": "error: serialization mismatch",
                        "redaction_status": "sanitized",
                        "truncated": True,
                    }
                ],
                "omitted": [
                    {"evidence_id": "evt_052_raw", "reason": "full raw output denied by policy"}
                ],
            }
        )
        rt = EvidenceExpandResponse.model_validate_json(response.model_dump_json())
        assert rt.expanded[0].truncated is True
        assert rt.omitted[0].reason == "full raw output denied by policy"

    def test_schema_version_required_on_request(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceExpandRequest.model_validate(
                {"request_id": "expand_001", "evidence_ids": ["evt_052"]}
            )

    def test_missing_evidence_ids_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            EvidenceExpandRequest.model_validate(
                {"schema_version": SCHEMA_V2, "request_id": "expand_001"}
            )
        assert "evidence_ids" in str(exc_info.value)


# ---------------------------------------------------------------------------
# SummaryValidateRequest / SummaryValidateResponse
# ---------------------------------------------------------------------------


class TestSummaryValidate:
    def test_request_round_trip(self) -> None:
        request = SummaryValidateRequest.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "request_id": "validate_001",
                "summary_ids": ["sum_001"],
                "checks": ["evidence_exists", "fact_grounding", "staleness"],
            }
        )
        rt = SummaryValidateRequest.model_validate_json(request.model_dump_json())
        assert rt.summary_ids == ["sum_001"]
        assert "staleness" in rt.checks

    def test_response_round_trip(self) -> None:
        response = SummaryValidateResponse.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "request_id": "validate_001",
                "results": [
                    {
                        "summary_id": "sum_001",
                        "status": "valid",
                        "score": 0.94,
                        "issues": [],
                        "checked_at": "2026-04-30T10:05:00Z",
                    }
                ],
            }
        )
        rt = SummaryValidateResponse.model_validate_json(response.model_dump_json())
        assert rt.results[0].score == pytest.approx(0.94)

    def test_schema_version_required_on_request(self) -> None:
        with pytest.raises(ValidationError):
            SummaryValidateRequest.model_validate(
                {"request_id": "validate_001", "summary_ids": ["sum_001"]}
            )


# ---------------------------------------------------------------------------
# SummarizeRequest / SummarizeResponse (Issue #82)
# ---------------------------------------------------------------------------


class TestSummarizeRequest:
    def test_minimal_round_trip(self) -> None:
        request = SummarizeRequest.model_validate(
            {"schema_version": SCHEMA_V2, "request_id": "summarize_001"}
        )
        rt = SummarizeRequest.model_validate_json(request.model_dump_json())
        assert rt.request_id == "summarize_001"
        assert rt.summary_level == "turn"
        assert rt.chunk_ids == []
        assert rt.recent_event_ids == []
        assert rt.parent_summary_ids == []
        assert isinstance(rt.policy, SummarizePolicy)
        assert rt.policy.require_evidence_ids is True
        assert rt.policy.separate_fact_and_hypothesis is True

    def test_full_anvil_turn_payload(self) -> None:
        request = SummarizeRequest.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "request_id": "summarize_002",
                "session_id": "sess_001",
                "turn_id": "turn_007",
                "agent": {"name": "anvil", "version": "0.4.0-rc1"},
                "repo": {"root": "/repo", "name": "demo"},
                "task": {"user_request": "fix session test", "mode": "act"},
                "summary_level": "turn",
                "chunk_ids": ["chunk_017", "chunk_018"],
                "recent_event_ids": ["evt_041", "evt_052"],
                "parent_summary_ids": ["sum_session_001"],
                "policy": {
                    "require_evidence_ids": True,
                    "separate_fact_and_hypothesis": True,
                    "include_failed_attempts": True,
                    "include_avoid_guidance": True,
                    "max_summary_chars": 2000,
                    "max_facts": 8,
                    "max_hypotheses": 4,
                },
            }
        )
        assert request.session_id == "sess_001"
        assert request.turn_id == "turn_007"
        assert request.agent is not None
        assert request.agent.name == "anvil"
        assert request.repo is not None
        assert request.repo.root == "/repo"
        assert request.task is not None
        assert request.task.user_request == "fix session test"
        assert request.summary_level == "turn"
        assert request.chunk_ids == ["chunk_017", "chunk_018"]
        assert request.recent_event_ids == ["evt_041", "evt_052"]
        assert request.parent_summary_ids == ["sum_session_001"]
        assert request.policy.max_summary_chars == 2000
        assert request.policy.max_facts == 8

    def test_schema_version_required(self) -> None:
        with pytest.raises(ValidationError):
            SummarizeRequest.model_validate({"request_id": "summarize_001"})

    def test_request_id_required(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            SummarizeRequest.model_validate({"schema_version": SCHEMA_V2})
        assert "request_id" in str(exc_info.value)

    def test_empty_payload_fails(self) -> None:
        with pytest.raises(ValidationError):
            SummarizeRequest.model_validate({})

    def test_policy_max_fields_reject_negative(self) -> None:
        with pytest.raises(ValidationError):
            SummarizePolicy.model_validate({"max_facts": -1})
        with pytest.raises(ValidationError):
            SummarizePolicy.model_validate({"max_summary_chars": -1})

    def test_unknown_policy_fields_preserved(self) -> None:
        policy = SummarizePolicy.model_validate({"allow_termination_when_unresolved": True})
        assert policy.model_dump()["allow_termination_when_unresolved"] is True

    def test_unknown_request_fields_preserved(self) -> None:
        request = SummarizeRequest.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "request_id": "summarize_003",
                "experiment_tag": "v0.4.0-canary",
            }
        )
        assert request.model_dump()["experiment_tag"] == "v0.4.0-canary"


class TestSummarizeResponse:
    def test_minimal_round_trip(self) -> None:
        response = SummarizeResponse.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "request_id": "summarize_001",
                "model_version": "photon-action-memory-v0.1.0-fallback",
                "sidecar_status": "not_implemented",
            }
        )
        rt = SummarizeResponse.model_validate_json(response.model_dump_json())
        assert rt.sidecar_status == "not_implemented"
        assert rt.summary is None
        assert rt.validation is None
        assert rt.warnings == []

    def test_full_payload_with_summary_and_validation(self) -> None:
        response = SummarizeResponse.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "request_id": "summarize_001",
                "model_version": "photon-action-memory-v0.4.0",
                "sidecar_status": "ok",
                "summary": {
                    "schema_version": SCHEMA_V2,
                    "summary_id": "sum_001",
                    "summary_level": "turn",
                },
                "validation": {
                    "summary_id": "sum_001",
                    "status": "valid",
                    "score": 0.94,
                },
                "warnings": [{"kind": "missing_evidence", "message": "fact 1 has no evidence_id"}],
            }
        )
        rt = SummarizeResponse.model_validate_json(response.model_dump_json())
        assert rt.summary is not None
        assert rt.summary.summary_id == "sum_001"
        assert rt.validation is not None
        assert rt.validation.score == pytest.approx(0.94)
        assert rt.warnings[0].kind == "missing_evidence"

    def test_schema_version_required(self) -> None:
        with pytest.raises(ValidationError):
            SummarizeResponse.model_validate(
                {
                    "request_id": "summarize_001",
                    "model_version": "fallback",
                    "sidecar_status": "ok",
                }
            )

    def test_unknown_fields_preserved(self) -> None:
        response = SummarizeResponse.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "request_id": "summarize_001",
                "model_version": "fallback",
                "sidecar_status": "ok",
                "trace_id": "trace-001",
            }
        )
        assert response.model_dump()["trace_id"] == "trace-001"


# ---------------------------------------------------------------------------
# Cross-cutting: unknown optional fields never break validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "base_payload", "extra"),
    [
        (
            ActionChunk,
            {
                "schema_version": SCHEMA_V2,
                "chunk_id": "c1",
                "session_id": "s1",
                "kind": "other",
                "summary": "test",
            },
            {"future_field": "value"},
        ),
        (
            EvidenceRef,
            {
                "schema_version": SCHEMA_V2,
                "evidence_id": "e1",
                "kind": "diff",
                "summary": "diff",
            },
            {"future_field": "value"},
        ),
        (
            ActionSummary,
            {"schema_version": SCHEMA_V2, "summary_id": "s1"},
            {"future_field": "value"},
        ),
        (
            ContextAdmissionDecision,
            {
                "schema_version": SCHEMA_V2,
                "decision_id": "d1",
                "item_id": "i1",
                "item_kind": "warning",
                "decision": "defer",
            },
            {"future_field": "value"},
        ),
        (
            ContextPack,
            {**minimal_context_pack()},
            {"future_field": "value"},
        ),
    ],
)
def test_unknown_optional_fields_do_not_break_validation(
    model: type[BaseModel],
    base_payload: dict[str, object],
    extra: dict[str, object],
) -> None:
    instance = model.model_validate({**base_payload, **extra})
    dumped = instance.model_dump()
    assert dumped["future_field"] == "value"


# ---------------------------------------------------------------------------
# Cross-cutting: wrong schema version always fails
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "base_payload"),
    [
        (
            ActionChunk,
            {
                "schema_version": "action-memory.v1",
                "chunk_id": "c1",
                "session_id": "s1",
                "kind": "other",
                "summary": "test",
            },
        ),
        (
            EvidenceRef,
            {
                "schema_version": "action-memory.v1",
                "evidence_id": "e1",
                "kind": "diff",
                "summary": "diff",
            },
        ),
        (
            ActionSummary,
            {"schema_version": "action-memory.v1", "summary_id": "s1"},
        ),
        (
            ContextPack,
            {
                "schema_version": "action-memory.v1",
                "request_id": "r1",
                "mode": "summary_only",
                "token_budget": minimal_token_budget(),
            },
        ),
    ],
)
def test_wrong_schema_version_fails(
    model: type[BaseModel], base_payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(base_payload)


# ---------------------------------------------------------------------------
# Issue #33: JSON fixture round-trip validation
# ---------------------------------------------------------------------------


def test_action_chunk_fixture_round_trip() -> None:
    raw = (FIXTURE_ROOT / "action_chunk_valid.json").read_text()
    chunk = ActionChunk.model_validate_json(raw)
    rt = ActionChunk.model_validate_json(chunk.model_dump_json())

    assert rt.schema_version == SCHEMA_V2
    assert rt.chunk_id == "chunk_017"
    assert rt.kind == "repo_search"
    assert rt.outcome == "useful"
    assert rt.risk == "low"
    assert rt.event_ids == ["evt_041", "evt_042", "evt_043"]
    assert rt.redaction_status == "sanitized"


def test_evidence_ref_fixture_round_trip() -> None:
    raw = (FIXTURE_ROOT / "evidence_ref_valid.json").read_text()
    ref = EvidenceRef.model_validate_json(raw)
    rt = EvidenceRef.model_validate_json(ref.model_dump_json())

    assert rt.schema_version == SCHEMA_V2
    assert rt.evidence_id == "evt_052"
    assert rt.kind == "test_output"
    assert rt.expand_policy == "on_demand_only"
    assert rt.max_expand_chars == 1200
    assert rt.staleness.status == "valid"
    assert rt.locator is not None
    assert rt.locator.file == "tests/session_persistence.rs"
    assert rt.locator.line_start == 42


def test_action_summary_fixture_round_trip() -> None:
    raw = (FIXTURE_ROOT / "action_summary_valid.json").read_text()
    summary = ActionSummary.model_validate_json(raw)
    rt = ActionSummary.model_validate_json(summary.model_dump_json())

    assert rt.schema_version == SCHEMA_V2
    assert rt.summary_id == "sum_001"
    assert rt.task_signature == "fix-session-persistence-test"
    assert rt.summary_level == "chunk"
    assert rt.validity.status == "valid"
    assert rt.token_cost is not None
    assert rt.token_cost.tokens_saved_vs_raw == 4960


def test_context_pack_fixture_round_trip() -> None:
    raw = (FIXTURE_ROOT / "context_pack_omits_raw.json").read_text()
    pack = ContextPack.model_validate_json(raw)
    rt = ContextPack.model_validate_json(pack.model_dump_json())

    assert rt.schema_version == SCHEMA_V2
    assert rt.request_id == "turn_123"
    assert rt.mode == "summary_only"


def test_action_summary_fixture_separates_facts_and_hypotheses() -> None:
    raw = (FIXTURE_ROOT / "action_summary_valid.json").read_text()
    summary = ActionSummary.model_validate_json(raw)

    assert summary.facts
    assert summary.hypotheses
    assert summary.failed_attempts
    assert summary.avoid

    assert summary.facts[0].evidence_ids
    assert 0.0 <= summary.facts[0].confidence <= 1.0
    assert summary.hypotheses[0].evidence_ids
    assert summary.hypotheses[0].status == "open"
    assert summary.failed_attempts[0].evidence_ids
    assert summary.avoid[0].evidence_ids


def test_context_pack_fixture_omits_raw_tool_output() -> None:
    raw = (FIXTURE_ROOT / "context_pack_omits_raw.json").read_text()
    pack = ContextPack.model_validate_json(raw)

    item_kinds = {item.kind for item in pack.items}
    omitted_kinds = {omitted.kind for omitted in pack.omitted}

    assert "raw_tool_output" not in item_kinds
    assert "raw_tool_output" in omitted_kinds
    assert pack.token_budget.tokens_saved_vs_raw is not None
    assert pack.token_budget.tokens_saved_vs_raw > 0


# ---------------------------------------------------------------------------
# Issue #71: shared fixture round-trip validation (schema drift detection)
# ---------------------------------------------------------------------------


def test_shared_evaluate_shadow_not_injected_round_trip() -> None:
    raw = (SHARED_FIXTURE_ROOT / "evaluate_shadow_not_injected.json").read_text()
    req = EvaluateRequest.model_validate_json(raw)
    rt = EvaluateRequest.model_validate_json(req.model_dump_json())

    assert rt.schema_version == SCHEMA_V2
    assert rt.agent is not None
    assert rt.agent.name == "anvil"
    assert rt.context_pack_event is not None
    assert rt.context_pack_event.adoption_status == "shadow_not_injected"
    assert rt.context_pack_event.ignored_reason == "shadow_mode_no_injection"
    assert rt.context_pack_event.items_adopted_count == 0
    assert rt.context_pack_event.latency_ms == pytest.approx(42.0)


def test_shared_context_pack_request_with_raw_log_round_trip() -> None:
    raw = (SHARED_FIXTURE_ROOT / "context_pack_request_with_raw_log.json").read_text()
    req = ContextPackRequest.model_validate_json(raw)
    rt = ContextPackRequest.model_validate_json(req.model_dump_json())

    assert rt.schema_version == SCHEMA_V2
    assert rt.request_id == "shared-pack-raw-001"
    assert rt.agent is not None
    assert rt.agent.name == "anvil"
