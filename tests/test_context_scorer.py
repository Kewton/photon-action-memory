"""Smoke tests for context_scorer: FallbackContextScorer and injectable scorer."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionSummary,
    AvoidGuidance,
    EvidenceRef,
    Fact,
    FailedAttempt,
    Hypothesis,
    StalenessStatus,
    Validity,
)
from photon_action_memory.models.context_scorer import (
    AdmissionScore,
    ContextScorerProtocol,
    EvidenceExpansionScore,
    FallbackContextScorer,
    ScoringEvent,
    StalenessRiskScore,
    SummaryUsefulnessScore,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _summary(
    summary_id: str = "sum-001",
    *,
    facts: list[Fact] | None = None,
    hypotheses: list[Hypothesis] | None = None,
    failed_attempts: list[FailedAttempt] | None = None,
    avoid: list[AvoidGuidance] | None = None,
    validity_status: str = "valid",
) -> ActionSummary:
    return ActionSummary(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        summary_id=summary_id,
        session_id="sess-1",
        facts=facts or [],
        hypotheses=hypotheses or [],
        failed_attempts=failed_attempts or [],
        avoid=avoid or [],
        validity=Validity(status=validity_status),
    )


def _fact(text: str = "a fact") -> Fact:
    return Fact(text=text, evidence_ids=["ev-1"])


def _hypothesis(text: str = "a hypothesis") -> Hypothesis:
    return Hypothesis(text=text, confidence=0.5)


def _failed(action: str = "grep foo") -> FailedAttempt:
    return FailedAttempt(action=action, outcome="error", evidence_ids=[])


def _avoid(action: str = "open large_file") -> AvoidGuidance:
    return AvoidGuidance(action=action, reason="too expensive")


def _evidence_ref(
    evidence_id: str = "evd-001",
    *,
    expand_policy: str = "on_demand_only",
    staleness_status: str = "unknown",
) -> EvidenceRef:
    return EvidenceRef(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        evidence_id=evidence_id,
        kind="tool_result",
        summary="some evidence",
        expand_policy=expand_policy,
        staleness=StalenessStatus(status=staleness_status),
    )


# ---------------------------------------------------------------------------
# FallbackContextScorer — score_admission
# ---------------------------------------------------------------------------


def test_admission_empty_input_returns_empty_list() -> None:
    scorer = FallbackContextScorer()
    assert scorer.score_admission([]) == []


def test_admission_no_content_returns_zero_score() -> None:
    scorer = FallbackContextScorer()
    results = scorer.score_admission([_summary()])
    assert len(results) == 1
    assert results[0].score == pytest.approx(0.0)


def test_admission_with_facts_returns_positive_score() -> None:
    scorer = FallbackContextScorer()
    results = scorer.score_admission([_summary(facts=[_fact(), _fact()])])
    assert results[0].score > 0.0


def test_admission_stale_summary_scores_lower_than_valid() -> None:
    scorer = FallbackContextScorer()
    valid = _summary("sum-v", facts=[_fact(), _fact()], validity_status="valid")
    stale = _summary("sum-s", facts=[_fact(), _fact()], validity_status="stale")
    valid_score = scorer.score_admission([valid])[0].score
    stale_score = scorer.score_admission([stale])[0].score
    assert stale_score < valid_score


def test_admission_contradicted_summary_scores_lower_than_stale() -> None:
    scorer = FallbackContextScorer()
    stale = _summary("sum-s", facts=[_fact()], validity_status="stale")
    contradicted = _summary("sum-c", facts=[_fact()], validity_status="contradicted")
    assert (
        scorer.score_admission([contradicted])[0].score < scorer.score_admission([stale])[0].score
    )


def test_admission_scores_clamped_to_unit_interval() -> None:
    scorer = FallbackContextScorer()
    rich = _summary(
        facts=[_fact()] * 10,
        hypotheses=[_hypothesis()] * 10,
        failed_attempts=[_failed()] * 10,
    )
    result = scorer.score_admission([rich])[0]
    assert 0.0 <= result.score <= 1.0


def test_admission_is_deterministic() -> None:
    scorer = FallbackContextScorer()
    s = _summary(facts=[_fact()])
    assert scorer.score_admission([s])[0].score == scorer.score_admission([s])[0].score


def test_admission_preserves_summary_id() -> None:
    scorer = FallbackContextScorer()
    results = scorer.score_admission([_summary("my-id", facts=[_fact()])])
    assert results[0].summary_id == "my-id"


def test_admission_returns_one_result_per_summary() -> None:
    scorer = FallbackContextScorer()
    summaries = [_summary(f"sum-{i}", facts=[_fact()]) for i in range(4)]
    assert len(scorer.score_admission(summaries)) == 4


# ---------------------------------------------------------------------------
# FallbackContextScorer — score_evidence_expansion
# ---------------------------------------------------------------------------


def test_expansion_empty_input_returns_empty_list() -> None:
    scorer = FallbackContextScorer()
    assert scorer.score_evidence_expansion([]) == []


def test_expansion_deny_policy_returns_zero() -> None:
    scorer = FallbackContextScorer()
    result = scorer.score_evidence_expansion([_evidence_ref(expand_policy="deny")])[0]
    assert result.score == pytest.approx(0.0)


def test_expansion_always_policy_returns_high_score() -> None:
    scorer = FallbackContextScorer()
    result = scorer.score_evidence_expansion(
        [_evidence_ref(expand_policy="always", staleness_status="valid")]
    )[0]
    assert result.score > 0.5


def test_expansion_on_demand_policy_returns_mid_score() -> None:
    scorer = FallbackContextScorer()
    result = scorer.score_evidence_expansion(
        [_evidence_ref(expand_policy="on_demand_only", staleness_status="valid")]
    )[0]
    assert 0.0 < result.score <= 1.0


def test_expansion_stale_evidence_penalises_score() -> None:
    scorer = FallbackContextScorer()
    fresh = _evidence_ref("evd-f", expand_policy="on_demand_only", staleness_status="valid")
    stale = _evidence_ref("evd-s", expand_policy="on_demand_only", staleness_status="stale")
    fresh_score = scorer.score_evidence_expansion([fresh])[0].score
    stale_score = scorer.score_evidence_expansion([stale])[0].score
    assert stale_score < fresh_score


def test_expansion_preserves_evidence_id() -> None:
    scorer = FallbackContextScorer()
    results = scorer.score_evidence_expansion([_evidence_ref("my-evd")])
    assert results[0].evidence_id == "my-evd"


# ---------------------------------------------------------------------------
# FallbackContextScorer — score_summary_usefulness
# ---------------------------------------------------------------------------


def test_usefulness_empty_input_returns_empty_list() -> None:
    scorer = FallbackContextScorer()
    assert scorer.score_summary_usefulness([]) == []


def test_usefulness_no_task_text_returns_low_score() -> None:
    scorer = FallbackContextScorer()
    result = scorer.score_summary_usefulness([_summary(facts=[_fact()])], task_text="")[0]
    # With no task context richness is halved
    assert result.score < 0.5


def test_usefulness_matching_task_text_raises_score() -> None:
    scorer = FallbackContextScorer()
    s = _summary(facts=[_fact("fix the failing test")])
    low = scorer.score_summary_usefulness([s], task_text="")[0].score
    high = scorer.score_summary_usefulness([s], task_text="fix the failing test")[0].score
    assert high > low


def test_usefulness_no_overlap_falls_back_to_richness() -> None:
    scorer = FallbackContextScorer()
    s = _summary(facts=[_fact("xyz abc")])
    result = scorer.score_summary_usefulness([s], task_text="unrelated topic words")[0]
    assert result.score >= 0.0


def test_usefulness_is_deterministic() -> None:
    scorer = FallbackContextScorer()
    s = _summary(facts=[_fact("read file")])
    r1 = scorer.score_summary_usefulness([s], task_text="read the file")[0].score
    r2 = scorer.score_summary_usefulness([s], task_text="read the file")[0].score
    assert r1 == pytest.approx(r2)


# ---------------------------------------------------------------------------
# FallbackContextScorer — score_staleness_risk
# ---------------------------------------------------------------------------


def test_staleness_risk_empty_input_returns_empty_list() -> None:
    scorer = FallbackContextScorer()
    assert scorer.score_staleness_risk([]) == []


def test_staleness_risk_valid_returns_zero() -> None:
    scorer = FallbackContextScorer()
    result = scorer.score_staleness_risk([_summary(validity_status="valid")])[0]
    assert result.risk == pytest.approx(0.0)


def test_staleness_risk_contradicted_returns_one() -> None:
    scorer = FallbackContextScorer()
    result = scorer.score_staleness_risk([_summary(validity_status="contradicted")])[0]
    assert result.risk == pytest.approx(1.0)


def test_staleness_risk_stale_returns_high_risk() -> None:
    scorer = FallbackContextScorer()
    result = scorer.score_staleness_risk([_summary(validity_status="stale")])[0]
    assert result.risk > 0.5


def test_staleness_risk_partial_between_valid_and_stale() -> None:
    scorer = FallbackContextScorer()
    valid_risk = scorer.score_staleness_risk([_summary(validity_status="valid")])[0].risk
    partial_risk = scorer.score_staleness_risk([_summary(validity_status="partial")])[0].risk
    stale_risk = scorer.score_staleness_risk([_summary(validity_status="stale")])[0].risk
    assert valid_risk < partial_risk < stale_risk


def test_staleness_risk_unknown_status_returns_mid_risk() -> None:
    scorer = FallbackContextScorer()
    result = scorer.score_staleness_risk([_summary(validity_status="unknown")])[0]
    assert 0.0 < result.risk < 1.0


def test_staleness_risk_preserves_summary_id() -> None:
    scorer = FallbackContextScorer()
    results = scorer.score_staleness_risk([_summary("id-xyz")])
    assert results[0].summary_id == "id-xyz"


# ---------------------------------------------------------------------------
# Eval hook
# ---------------------------------------------------------------------------


def test_eval_hook_called_for_each_scored_item() -> None:
    events: list[ScoringEvent] = []
    scorer = FallbackContextScorer(eval_hook=events.append)
    summaries = [_summary(f"sum-{i}", facts=[_fact()]) for i in range(3)]
    scorer.score_admission(summaries)
    assert len(events) == 3


def test_eval_hook_receives_correct_scorer_kind_admission() -> None:
    events: list[ScoringEvent] = []
    scorer = FallbackContextScorer(eval_hook=events.append)
    scorer.score_admission([_summary(facts=[_fact()])])
    assert events[0].scorer_kind == "admission"


def test_eval_hook_receives_correct_scorer_kind_evidence_expansion() -> None:
    events: list[ScoringEvent] = []
    scorer = FallbackContextScorer(eval_hook=events.append)
    scorer.score_evidence_expansion([_evidence_ref()])
    assert events[0].scorer_kind == "evidence_expansion"


def test_eval_hook_receives_correct_scorer_kind_summary_usefulness() -> None:
    events: list[ScoringEvent] = []
    scorer = FallbackContextScorer(eval_hook=events.append)
    scorer.score_summary_usefulness([_summary(facts=[_fact()])], task_text="task")
    assert events[0].scorer_kind == "summary_usefulness"


def test_eval_hook_receives_correct_scorer_kind_staleness_risk() -> None:
    events: list[ScoringEvent] = []
    scorer = FallbackContextScorer(eval_hook=events.append)
    scorer.score_staleness_risk([_summary()])
    assert events[0].scorer_kind == "staleness_risk"


def test_eval_hook_event_carries_item_id_and_score() -> None:
    events: list[ScoringEvent] = []
    scorer = FallbackContextScorer(eval_hook=events.append)
    scorer.score_staleness_risk([_summary("sum-track", validity_status="stale")])
    assert events[0].item_id == "sum-track"
    assert events[0].score == pytest.approx(0.8)


def test_no_eval_hook_does_not_raise() -> None:
    scorer = FallbackContextScorer()
    scorer.score_admission([_summary(facts=[_fact()])])


def test_eval_hook_not_called_for_empty_input() -> None:
    events: list[ScoringEvent] = []
    scorer = FallbackContextScorer(eval_hook=events.append)
    scorer.score_admission([])
    scorer.score_evidence_expansion([])
    scorer.score_summary_usefulness([])
    scorer.score_staleness_risk([])
    assert events == []


# ---------------------------------------------------------------------------
# ContextScorerProtocol — injectable scorer
# ---------------------------------------------------------------------------


class _FixedScorer:
    """Injectable scorer that always returns a fixed score; satisfies Protocol."""

    def score_admission(
        self,
        summaries: Sequence[ActionSummary],
        *,
        task_text: str = "",
    ) -> list[AdmissionScore]:
        return [AdmissionScore(s.summary_id, 0.9, "fixed") for s in summaries]

    def score_evidence_expansion(
        self,
        evidence_refs: Sequence[EvidenceRef],
        *,
        task_text: str = "",
    ) -> list[EvidenceExpansionScore]:
        return [EvidenceExpansionScore(r.evidence_id, 0.8, "fixed") for r in evidence_refs]

    def score_summary_usefulness(
        self,
        summaries: Sequence[ActionSummary],
        *,
        task_text: str = "",
    ) -> list[SummaryUsefulnessScore]:
        return [SummaryUsefulnessScore(s.summary_id, 0.7, "fixed") for s in summaries]

    def score_staleness_risk(
        self,
        summaries: Sequence[ActionSummary],
    ) -> list[StalenessRiskScore]:
        return [StalenessRiskScore(s.summary_id, 0.1, "fixed") for s in summaries]


def test_fallback_scorer_satisfies_protocol() -> None:
    assert isinstance(FallbackContextScorer(), ContextScorerProtocol)


def test_injectable_scorer_satisfies_protocol() -> None:
    assert isinstance(_FixedScorer(), ContextScorerProtocol)


def test_injectable_scorer_returns_fixed_admission_score() -> None:
    scorer: ContextScorerProtocol = _FixedScorer()
    results = scorer.score_admission([_summary(facts=[_fact()])])
    assert results[0].score == pytest.approx(0.9)


def test_injectable_scorer_returns_fixed_staleness_risk() -> None:
    scorer: ContextScorerProtocol = _FixedScorer()
    results = scorer.score_staleness_risk([_summary(validity_status="stale")])
    assert results[0].risk == pytest.approx(0.1)


def test_injectable_scorer_can_be_called_through_protocol_type() -> None:
    def _run(scorer: ContextScorerProtocol, s: ActionSummary) -> float:
        return scorer.score_admission([s])[0].score

    assert _run(_FixedScorer(), _summary(facts=[_fact()])) == pytest.approx(0.9)
    assert _run(FallbackContextScorer(), _summary()) == pytest.approx(0.0)
