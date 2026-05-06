"""Neutral ContextPack integration contract for LLM prompt construction.

Defines the three-step calling sequence any coding agent should follow when
integrating PHOTON Action Memory ContextPack into its prompt-building pipeline.
Anvil is used as one concrete example; the contract is intentionally
agent-neutral and applies to any tool-use agent with a sidecar.

Calling sequence
----------------
1. POST /v1/context/pack  — before assembling the LLM prompt (required)
2. POST /v1/evidence/expand — when pack items need more detail (optional)
3. POST /v1/evaluate       — after the turn completes to log adoption/outcome (required)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

IntegrationStepKind = Literal["context_pack", "evidence_expand", "evaluate"]

REQUIRED_STEPS: frozenset[IntegrationStepKind] = frozenset({"context_pack", "evaluate"})
OPTIONAL_STEPS: frozenset[IntegrationStepKind] = frozenset({"evidence_expand"})


@dataclass(frozen=True)
class IntegrationStep:
    """One named step in the ContextPack integration sequence."""

    kind: IntegrationStepKind
    endpoint: str
    when: str
    required: bool


@dataclass(frozen=True)
class IntegrationContract:
    """Full ContextPack integration contract.

    Any coding agent that embeds PHOTON Action Memory should execute these
    steps in order for every LLM turn where a ContextPack is requested.
    Skipping required steps breaks adoption tracking and degrades eval signal.
    """

    steps: tuple[IntegrationStep, ...]
    invariants: tuple[str, ...]


_CONTRACT_STEPS: tuple[IntegrationStep, ...] = (
    IntegrationStep(
        kind="context_pack",
        endpoint="POST /v1/context/pack",
        when="Before assembling the LLM prompt for the current turn.",
        required=True,
    ),
    IntegrationStep(
        kind="evidence_expand",
        endpoint="POST /v1/evidence/expand",
        when=(
            "After receiving the ContextPack, when one or more items carry "
            "expand_policy='on_demand_only' and the agent needs the full snippet "
            "before including the item in the prompt."
        ),
        required=False,
    ),
    IntegrationStep(
        kind="evaluate",
        endpoint="POST /v1/evaluate",
        when=(
            "After the LLM responds and the agent has determined whether the "
            "ContextPack items were adopted (injected), partially used, or ignored."
        ),
        required=True,
    ),
)

_CONTRACT_INVARIANTS: tuple[str, ...] = (
    "context_pack must be called before the LLM prompt is assembled.",
    "evidence_expand may be omitted; call it only when items signal on_demand_only.",
    "evaluate must be called after every turn; omitting it breaks adoption tracking.",
    (
        "The context_pack_request_id in EvaluateRequest.context_pack_event "
        "must reference the request_id from the preceding ContextPackRequest."
    ),
)

CONTEXT_PACK_CONTRACT: IntegrationContract = IntegrationContract(
    steps=_CONTRACT_STEPS,
    invariants=_CONTRACT_INVARIANTS,
)


def validate_call_sequence(
    step_kinds: list[IntegrationStepKind],
) -> list[str]:
    """Return a list of contract violations for the given calling sequence.

    An empty list means the sequence is valid.  Call this in tests or CI to
    verify that a recorded agent trace follows the integration contract.
    """
    violations: list[str] = []
    seen = set(step_kinds)

    for step in CONTEXT_PACK_CONTRACT.steps:
        if step.required and step.kind not in seen:
            violations.append(f"required step '{step.kind}' was not called")

    if "context_pack" in seen and "evaluate" in seen:
        try:
            cp_index = step_kinds.index("context_pack")
            ev_index = step_kinds.index("evaluate")
            if cp_index > ev_index:
                violations.append("'context_pack' must be called before 'evaluate'")
        except ValueError:
            pass

    if "evidence_expand" in seen and "context_pack" not in seen:
        violations.append("'evidence_expand' was called without a preceding 'context_pack' call")

    return violations


__all__ = [
    "CONTEXT_PACK_CONTRACT",
    "IntegrationContract",
    "IntegrationStep",
    "IntegrationStepKind",
    "OPTIONAL_STEPS",
    "REQUIRED_STEPS",
    "validate_call_sequence",
]
