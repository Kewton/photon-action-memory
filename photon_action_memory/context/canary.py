"""Canary-mode policy for low-risk Context Firewall injection.

The canary preset is intentionally conservative: only read/search/test
candidate hints, repeated exploration warnings, and summary-only memory are
eligible for prompt injection. Destructive, edit-approving, security-sensitive,
and raw stdout/stderr injection classes are denied.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    AdmissionPolicy,
    ContextAdmissionDecision,
)

CANARY_POLICY_NAME = "context_firewall_canary.v1"

AllowedCanaryClass = Literal[
    "read_candidate",
    "search_query_candidate",
    "test_command_candidate",
    "repeat_search_warning",
    "repeat_read_warning",
    "summary_only_memory",
]

DeniedCanaryClass = Literal[
    "destructive_shell_command",
    "edit_auto_approval",
    "security_sensitive_operation",
    "raw_full_stdout_injection",
    "raw_full_stderr_injection",
]

CANARY_ALLOWED_CLASSES: frozenset[str] = frozenset(
    {
        "read_candidate",
        "search_query_candidate",
        "test_command_candidate",
        "repeat_search_warning",
        "repeat_read_warning",
        "summary_only_memory",
    }
)

CANARY_DENIED_CLASSES: frozenset[str] = frozenset(
    {
        "destructive_shell_command",
        "edit_auto_approval",
        "security_sensitive_operation",
        "raw_full_stdout_injection",
        "raw_full_stderr_injection",
    }
)


class CanaryModeConfig(BaseModel):
    """Policy preset for low-risk Context Firewall canary mode."""

    model_config = ConfigDict(extra="ignore")

    policy_name: str = CANARY_POLICY_NAME
    enabled: bool = True
    shadow_mode: bool = True
    fail_open: bool = True
    mode: str = "summary_only"
    allowed_action_classes: set[str] = Field(default_factory=lambda: set(CANARY_ALLOWED_CLASSES))
    denied_action_classes: set[str] = Field(default_factory=lambda: set(CANARY_DENIED_CLASSES))


class CanaryCandidate(BaseModel):
    """One candidate context injection evaluated by canary mode."""

    model_config = ConfigDict(extra="ignore")

    candidate_id: str
    action_class: str
    item_kind: str = "warning"
    estimated_tokens: int | None = Field(default=None, ge=0)


CANARY_MODE_CONFIG = CanaryModeConfig()


def evaluate_canary_candidate(
    candidate: CanaryCandidate | Mapping[str, Any],
    *,
    config: CanaryModeConfig = CANARY_MODE_CONFIG,
) -> ContextAdmissionDecision:
    """Evaluate one candidate under the canary preset.

    The helper is fail-open for malformed or unknown classes: it returns a
    `defer` decision instead of raising so the caller can continue without
    injecting risky context.
    """
    try:
        parsed = (
            candidate
            if isinstance(candidate, CanaryCandidate)
            else CanaryCandidate.model_validate(candidate)
        )
    except Exception as exc:
        return _decision(
            item_id="unknown",
            item_kind="unknown",
            decision="defer",
            reason=f"canary fail-open: invalid candidate ({exc.__class__.__name__})",
            estimated_tokens=None,
            config=config,
        )

    if not config.enabled:
        return _decision(
            item_id=parsed.candidate_id,
            item_kind=parsed.item_kind,
            decision="defer",
            reason="canary policy disabled",
            estimated_tokens=parsed.estimated_tokens,
            config=config,
        )

    if parsed.action_class in config.denied_action_classes:
        return _decision(
            item_id=parsed.candidate_id,
            item_kind=parsed.item_kind,
            decision="deny",
            reason=f"canary denied action class: {parsed.action_class}",
            estimated_tokens=parsed.estimated_tokens,
            config=config,
        )

    if parsed.action_class in config.allowed_action_classes:
        return _decision(
            item_id=parsed.candidate_id,
            item_kind=parsed.item_kind,
            decision="admit",
            reason=f"canary allowed low-risk action class: {parsed.action_class}",
            estimated_tokens=parsed.estimated_tokens,
            config=config,
        )

    return _decision(
        item_id=parsed.candidate_id,
        item_kind=parsed.item_kind,
        decision="defer",
        reason=f"canary fail-open: unknown action class: {parsed.action_class}",
        estimated_tokens=parsed.estimated_tokens,
        config=config,
    )


def evaluate_canary_candidates(
    candidates: list[CanaryCandidate | Mapping[str, Any]],
    *,
    config: CanaryModeConfig = CANARY_MODE_CONFIG,
) -> list[ContextAdmissionDecision]:
    """Evaluate candidates in order under the canary preset."""
    return [evaluate_canary_candidate(candidate, config=config) for candidate in candidates]


def _decision(
    *,
    item_id: str,
    item_kind: str,
    decision: str,
    reason: str,
    estimated_tokens: int | None,
    config: CanaryModeConfig,
) -> ContextAdmissionDecision:
    return ContextAdmissionDecision(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        decision_id=f"canary-{item_id}",
        item_id=item_id,
        item_kind=item_kind,
        decision=decision,
        reason=reason,
        estimated_tokens=estimated_tokens,
        policy=AdmissionPolicy(
            raw_evidence_policy="raw_tool_log_default_deny",
            detail_level=config.policy_name,
        ),
    )


__all__ = [
    "CANARY_ALLOWED_CLASSES",
    "CANARY_DENIED_CLASSES",
    "CANARY_MODE_CONFIG",
    "CANARY_POLICY_NAME",
    "CanaryCandidate",
    "CanaryModeConfig",
    "evaluate_canary_candidate",
    "evaluate_canary_candidates",
]
