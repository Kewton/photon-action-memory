"""Pluggable ActionSummary generator boundary.

Default behaviour stays deterministic via :class:`RuleBasedSummaryGenerator`,
which is a one-line wrapper over the existing :class:`ActionSummaryBuilder`.
An optional LLM-backed generator can be enabled by setting
``PHOTON_SUMMARY_GENERATOR=llm`` — see
:mod:`photon_action_memory.memory.llm_draft_summary`.

The generator interface returns a ``(summary, report)`` tuple so callers can
emit telemetry without exposing prompt content, raw model output, or
exception details. Fallback reasons are a closed enum so downstream
dashboards can rely on a stable label set.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from photon_action_memory.api.schema_v2 import ActionChunk, ActionSummary
from photon_action_memory.memory.summaries import ActionSummaryBuilder

SummaryGeneratorMode = Literal["rule_based", "llm"]

SummaryGeneratorFallbackReason = Literal[
    "mlx_unavailable",
    "model_unavailable",
    "generation_exception",
    "empty_output",
    "invalid_json",
    "schema_validation_failed",
    "quality_gate_rejected",
    "fidelity_invalid",
    "disabled",
]

SUMMARY_GENERATOR_ENV = "PHOTON_SUMMARY_GENERATOR"


class SummaryGenerationAborted(RuntimeError):
    """Raised when the LLM path fails and policy is ``abort``."""


@dataclass(frozen=True)
class SummaryGeneratorReport:
    """Telemetry describing which generator produced an ``ActionSummary``."""

    generator_used: SummaryGeneratorMode
    fallback_reason: SummaryGeneratorFallbackReason | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


class SummaryGeneratorProtocol(Protocol):
    """Convert one :class:`ActionChunk` into an :class:`ActionSummary`.

    ``evidence_records`` is optional auxiliary context (the same shape used by
    :class:`SummaryFidelityChecker`). Generators that do not need it may
    ignore it.
    """

    def build(
        self,
        chunk: ActionChunk,
        *,
        summary_id: str | None = None,
        evidence_records: Sequence[Mapping[str, Any]] | None = None,
    ) -> tuple[ActionSummary, SummaryGeneratorReport]: ...


class RuleBasedSummaryGenerator:
    """Deterministic generator that preserves the v0.2 contract.

    This is the v0.4.0 default and the fail-open fallback target for every
    LLM error path. The implementation is a thin wrapper so behaviour is
    byte-identical to the historical :class:`ActionSummaryBuilder`.
    """

    def __init__(self, builder: ActionSummaryBuilder | None = None) -> None:
        self._builder = builder or ActionSummaryBuilder()

    def build(
        self,
        chunk: ActionChunk,
        *,
        summary_id: str | None = None,
        evidence_records: Sequence[Mapping[str, Any]] | None = None,  # noqa: ARG002
    ) -> tuple[ActionSummary, SummaryGeneratorReport]:
        summary = self._builder.build(chunk, summary_id=summary_id)
        return summary, SummaryGeneratorReport(generator_used="rule_based")


def _resolve_mode(env: Mapping[str, str]) -> SummaryGeneratorMode:
    """Read ``PHOTON_SUMMARY_GENERATOR`` from ``env``; default to rule_based.

    Unknown values fall back to ``rule_based`` so a typo never silently
    enables the LLM path.
    """
    raw = (env.get(SUMMARY_GENERATOR_ENV) or "").strip().lower()
    if raw == "llm":
        return "llm"
    return "rule_based"


def make_summary_generator(
    env: Mapping[str, str] | None = None,
) -> SummaryGeneratorProtocol:
    """Build the generator the rest of the app should call.

    When ``llm`` is requested but construction itself fails (missing MLX,
    missing model, invalid config), the factory returns a wrapper that
    always delegates to the rule-based generator and labels every report
    with the proper fallback reason. Callers therefore never need to
    handle construction errors.
    """
    environment = env if env is not None else os.environ
    mode = _resolve_mode(environment)
    if mode == "rule_based":
        return RuleBasedSummaryGenerator()

    # Lazy import keeps the optional MLX dependency truly optional —
    # importing this module must never trigger an MLX import.
    from photon_action_memory.memory.llm_draft_summary import (
        LLMDraftSummaryGenerator,
        build_llm_draft_config,
    )

    config = build_llm_draft_config(environment)
    try:
        return LLMDraftSummaryGenerator.from_config(config)
    except Exception as exc:  # noqa: BLE001 — boundary; reason classified below
        reason = _classify_construction_failure(exc)
        return _AlwaysFallbackGenerator(reason=reason)


def _classify_construction_failure(exc: Exception) -> SummaryGeneratorFallbackReason:
    name = type(exc).__name__
    if name == "MlxUnavailable":
        return "mlx_unavailable"
    if name == "ModelUnavailable":
        return "model_unavailable"
    return "generation_exception"


@dataclass(frozen=True)
class _AlwaysFallbackGenerator:
    """Generator that always falls back to rule_based with a fixed reason.

    Used when the LLM generator could not even be constructed (e.g. MLX is
    not installed). It still satisfies :class:`SummaryGeneratorProtocol` so
    the call sites do not need to branch on construction outcome.
    """

    reason: SummaryGeneratorFallbackReason
    _fallback: RuleBasedSummaryGenerator = field(default_factory=RuleBasedSummaryGenerator)

    def build(
        self,
        chunk: ActionChunk,
        *,
        summary_id: str | None = None,
        evidence_records: Sequence[Mapping[str, Any]] | None = None,
    ) -> tuple[ActionSummary, SummaryGeneratorReport]:
        summary, _ = self._fallback.build(
            chunk,
            summary_id=summary_id,
            evidence_records=evidence_records,
        )
        return summary, SummaryGeneratorReport(
            generator_used="rule_based",
            fallback_reason=self.reason,
        )


__all__ = [
    "SUMMARY_GENERATOR_ENV",
    "RuleBasedSummaryGenerator",
    "SummaryGenerationAborted",
    "SummaryGeneratorFallbackReason",
    "SummaryGeneratorMode",
    "SummaryGeneratorProtocol",
    "SummaryGeneratorReport",
    "make_summary_generator",
]
