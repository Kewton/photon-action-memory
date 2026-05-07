"""Tests for Anvil evaluate feedback aggregation and FeedbackAdjustedContextScorer.

Acceptance criteria covered:
- aggregate_anvil_feedback builds correct quality signal from Anvil evaluate fixture.
- fail-open/error/shadow_not_injected/not_available turns excluded from quality signal.
- FeedbackAdjustedContextScorer boosts valid-item scores via positive feedback.
- stale/contradicted items are hard-capped and never score-recover via feedback.
- Staleness risk is never adjusted by feedback.
- Deterministic ranking improvement: feedback scorer ranks valid items higher.
- PackFeedback stores aggregate-safe features (counts + rates, no raw content).
- Per-evidence quality signals are derived from expansion × outcome correlation.
"""

from __future__ import annotations

import json
from pathlib import Path

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
from photon_action_memory.eval.anvil_feedback import (
    EXCLUDED_QUALITY_STATUSES,
    EvidenceFeedback,
    PackFeedback,
    aggregate_anvil_feedback,
)
from photon_action_memory.eval.context_pack_log import ContextPackEvalRecord
from photon_action_memory.models.context_scorer import (
    ContextScorerProtocol,
    FallbackContextScorer,
    ScoringEvent,
)
from photon_action_memory.ranking.feedback import (
    CONTRADICTED_MAX_SCORE,
    STALE_MAX_SCORE,
    FeedbackAdjustedContextScorer,
    apply_feedback_boost,
)

FIXTURES_V2 = Path(__file__).parent / "fixtures" / "v0.2"


# ---------------------------------------------------------------------------
# Helpers
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


def _record(
    status: str = "adopted",
    outcome: str | None = "success",
    evidence_ids: list[str] | None = None,
) -> ContextPackEvalRecord:
    return ContextPackEvalRecord(
        context_pack_request_id=f"pack-{status}",
        adoption_status=status,
        outcome=outcome,
        evidence_expand_requested=bool(evidence_ids),
        evidence_ids_expanded=evidence_ids or [],
    )


def _high_quality_feedback() -> PackFeedback:
    return aggregate_anvil_feedback([_record("adopted", "success"), _record("adopted", "success")])


def _zero_quality_feedback() -> PackFeedback:
    return aggregate_anvil_feedback([_record("ignored", "failure")])


# ---------------------------------------------------------------------------
# aggregate_anvil_feedback — basic correctness
# ---------------------------------------------------------------------------


def test_aggregate_empty_returns_zero_feedback() -> None:
    fb = aggregate_anvil_feedback([])
    assert fb.total_turns == 0
    assert fb.quality_turns == 0
    assert fb.quality_score == 0.0
    assert fb.evidence_feedback == {}


def test_aggregate_all_success_returns_quality_score_one() -> None:
    fb = aggregate_anvil_feedback([_record("adopted", "success"), _record("adopted", "success")])
    assert fb.total_turns == 2
    assert fb.quality_turns == 2
    assert fb.quality_score == pytest.approx(1.0)
    assert fb.adoption_count == 2
    assert fb.success_count == 2


def test_aggregate_mixed_computes_correct_quality_score() -> None:
    records = [
        _record("adopted", "success"),
        _record("adopted", "success"),
        _record("ignored", "failure"),
    ]
    fb = aggregate_anvil_feedback(records)
    assert fb.total_turns == 3
    assert fb.quality_turns == 3
    assert fb.success_count == 2
    assert fb.quality_score == pytest.approx(2 / 3)


def test_aggregate_partial_counts_as_adoption() -> None:
    fb = aggregate_anvil_feedback([_record("partial", "success")])
    assert fb.adoption_count == 1


# ---------------------------------------------------------------------------
# Excluded quality statuses (acceptance criterion: fail-open excluded)
# ---------------------------------------------------------------------------


def test_excluded_quality_statuses_set_contains_expected() -> None:
    assert "error" in EXCLUDED_QUALITY_STATUSES
    assert "not_available" in EXCLUDED_QUALITY_STATUSES
    assert "shadow_not_injected" in EXCLUDED_QUALITY_STATUSES


def test_error_turns_excluded_from_quality_turns() -> None:
    records = [
        _record("adopted", "success"),
        _record("error", None),
    ]
    fb = aggregate_anvil_feedback(records)
    assert fb.total_turns == 2
    assert fb.quality_turns == 1
    assert fb.quality_score == pytest.approx(1.0)


def test_shadow_not_injected_excluded_from_quality_turns() -> None:
    records = [
        _record("adopted", "success"),
        _record("shadow_not_injected", None),
        _record("shadow_not_injected", None),
    ]
    fb = aggregate_anvil_feedback(records)
    assert fb.total_turns == 3
    assert fb.quality_turns == 1
    assert fb.success_count == 1


def test_not_available_excluded_from_quality_turns() -> None:
    records = [
        _record("not_available", None),
        _record("adopted", "success"),
    ]
    fb = aggregate_anvil_feedback(records)
    assert fb.quality_turns == 1


def test_all_excluded_turns_yields_zero_quality_score() -> None:
    records = [_record("error", None), _record("not_available", None)]
    fb = aggregate_anvil_feedback(records)
    assert fb.total_turns == 2
    assert fb.quality_turns == 0
    assert fb.quality_score == 0.0


# ---------------------------------------------------------------------------
# Evidence feedback
# ---------------------------------------------------------------------------


def test_evidence_feedback_tracks_expansion_count() -> None:
    records = [
        _record("adopted", "success", ["ev-001"]),
        _record("adopted", "success", ["ev-001"]),
    ]
    fb = aggregate_anvil_feedback(records)
    assert "ev-001" in fb.evidence_feedback
    assert fb.evidence_feedback["ev-001"].expansion_count == 2
    assert fb.evidence_feedback["ev-001"].success_count == 2
    assert fb.evidence_feedback["ev-001"].quality_score == pytest.approx(1.0)


def test_evidence_feedback_mixed_outcomes() -> None:
    records = [
        _record("adopted", "success", ["ev-001"]),
        _record("adopted", "failure", ["ev-001"]),
    ]
    fb = aggregate_anvil_feedback(records)
    ev = fb.evidence_feedback["ev-001"]
    assert ev.expansion_count == 2
    assert ev.success_count == 1
    assert ev.quality_score == pytest.approx(0.5)


def test_evidence_feedback_excludes_error_turn_expansions() -> None:
    records = [
        _record("adopted", "success", ["ev-001"]),
        _record("error", None, ["ev-001"]),
    ]
    fb = aggregate_anvil_feedback(records)
    # error turn is excluded from quality — evidence_feedback only counts quality turns
    assert fb.evidence_feedback["ev-001"].expansion_count == 1


def test_evidence_feedback_multiple_ids_per_turn() -> None:
    records = [_record("adopted", "success", ["ev-a", "ev-b"])]
    fb = aggregate_anvil_feedback(records)
    assert "ev-a" in fb.evidence_feedback
    assert "ev-b" in fb.evidence_feedback


def test_evidence_not_expanded_has_no_feedback_entry() -> None:
    fb = aggregate_anvil_feedback([_record("adopted", "success")])
    assert fb.evidence_feedback == {}


# ---------------------------------------------------------------------------
# Fixture validation
# ---------------------------------------------------------------------------


def test_feedback_fixture_validates_and_aggregates() -> None:
    raw = json.loads((FIXTURES_V2 / "anvil_evaluate_feedback.json").read_text())
    fb = aggregate_anvil_feedback(raw["records"])
    # 5 total, 2 excluded (error + shadow_not_injected) → 3 quality turns
    assert fb.total_turns == 5
    assert fb.quality_turns == 3
    assert fb.success_count == 2
    assert fb.quality_score == pytest.approx(2 / 3)


def test_feedback_fixture_evidence_feedback() -> None:
    raw = json.loads((FIXTURES_V2 / "anvil_evaluate_feedback.json").read_text())
    fb = aggregate_anvil_feedback(raw["records"])
    # ev-useful-001 expanded twice (both success), ev-useful-002 once (success)
    assert fb.evidence_feedback["ev-useful-001"].expansion_count == 2
    assert fb.evidence_feedback["ev-useful-001"].quality_score == pytest.approx(1.0)
    assert fb.evidence_feedback["ev-useful-002"].quality_score == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# apply_feedback_boost
# ---------------------------------------------------------------------------


def test_boost_increases_score_for_valid_item() -> None:
    boosted = apply_feedback_boost(0.3, "valid", 1.0)
    assert boosted > 0.3


def test_boost_clamped_to_one() -> None:
    boosted = apply_feedback_boost(0.95, "valid", 1.0)
    assert boosted <= 1.0


def test_boost_zero_quality_score_returns_base() -> None:
    base = 0.4
    assert apply_feedback_boost(base, "valid", 0.0) == pytest.approx(base)


def test_boost_stale_capped_at_stale_max() -> None:
    # Even maximum boost cannot push a stale item above STALE_MAX_SCORE
    boosted = apply_feedback_boost(0.20, "stale", 1.0)
    assert boosted <= STALE_MAX_SCORE


def test_boost_contradicted_capped_at_contradicted_max() -> None:
    boosted = apply_feedback_boost(0.10, "contradicted", 1.0)
    assert boosted <= CONTRADICTED_MAX_SCORE


def test_boost_unsafe_capped_at_contradicted_max() -> None:
    boosted = apply_feedback_boost(0.12, "unsafe", 1.0)
    assert boosted <= CONTRADICTED_MAX_SCORE


def test_boost_valid_and_unknown_uncapped() -> None:
    for status in ("valid", "partial", "unknown"):
        boosted = apply_feedback_boost(0.5, status, 1.0)
        assert boosted > STALE_MAX_SCORE, f"status={status} should be uncapped"


# ---------------------------------------------------------------------------
# FeedbackAdjustedContextScorer — admission
# ---------------------------------------------------------------------------


def test_feedback_scorer_satisfies_protocol() -> None:
    fb = _high_quality_feedback()
    scorer = FeedbackAdjustedContextScorer(fb)
    assert isinstance(scorer, ContextScorerProtocol)


def test_feedback_scorer_admission_boosts_valid_item() -> None:
    fb = _high_quality_feedback()
    base_scorer = FallbackContextScorer()
    adj_scorer = FeedbackAdjustedContextScorer(fb)
    s = _summary(facts=[_fact()])
    base_score = base_scorer.score_admission([s])[0].score
    adj_score = adj_scorer.score_admission([s])[0].score
    assert adj_score >= base_score


def test_feedback_scorer_admission_stale_cannot_recover() -> None:
    fb = _high_quality_feedback()
    adj_scorer = FeedbackAdjustedContextScorer(fb)
    # Rich stale summary — even with maximum feedback it must stay ≤ STALE_MAX_SCORE
    rich_stale = _summary(
        "stale-rich",
        facts=[_fact()] * 4,
        hypotheses=[_hypothesis()] * 4,
        validity_status="stale",
    )
    score = adj_scorer.score_admission([rich_stale])[0].score
    assert score <= STALE_MAX_SCORE


def test_feedback_scorer_admission_contradicted_cannot_recover() -> None:
    fb = _high_quality_feedback()
    adj_scorer = FeedbackAdjustedContextScorer(fb)
    rich_contradicted = _summary(
        "contr-rich",
        facts=[_fact()] * 4,
        validity_status="contradicted",
    )
    score = adj_scorer.score_admission([rich_contradicted])[0].score
    assert score <= CONTRADICTED_MAX_SCORE


def test_feedback_scorer_stale_scores_below_valid_always() -> None:
    fb = _high_quality_feedback()
    adj_scorer = FeedbackAdjustedContextScorer(fb)
    valid_s = _summary("v", facts=[_fact(), _fact()], validity_status="valid")
    stale_s = _summary("s", facts=[_fact(), _fact()], validity_status="stale")
    valid_score = adj_scorer.score_admission([valid_s])[0].score
    stale_score = adj_scorer.score_admission([stale_s])[0].score
    assert stale_score < valid_score


def test_feedback_scorer_zero_quality_does_not_boost() -> None:
    fb = _zero_quality_feedback()
    base_scorer = FallbackContextScorer()
    adj_scorer = FeedbackAdjustedContextScorer(fb)
    s = _summary(facts=[_fact()])
    base_score = base_scorer.score_admission([s])[0].score
    adj_score = adj_scorer.score_admission([s])[0].score
    assert adj_score == pytest.approx(base_score)


# ---------------------------------------------------------------------------
# FeedbackAdjustedContextScorer — evidence expansion
# ---------------------------------------------------------------------------


def test_feedback_scorer_expansion_uses_per_evidence_quality() -> None:
    records = [_record("adopted", "success", ["ev-seen"])]
    fb = aggregate_anvil_feedback(records)
    adj_scorer = FeedbackAdjustedContextScorer(fb)
    base_scorer = FallbackContextScorer()
    ref = _evidence_ref("ev-seen", staleness_status="valid")
    base_score = base_scorer.score_evidence_expansion([ref])[0].score
    adj_score = adj_scorer.score_evidence_expansion([ref])[0].score
    assert adj_score >= base_score


def test_feedback_scorer_expansion_stale_cannot_recover() -> None:
    fb = _high_quality_feedback()
    adj_scorer = FeedbackAdjustedContextScorer(fb)
    stale_ref = _evidence_ref("ev-stale", expand_policy="always", staleness_status="stale")
    score = adj_scorer.score_evidence_expansion([stale_ref])[0].score
    assert score <= STALE_MAX_SCORE


def test_feedback_scorer_expansion_unseen_evidence_uses_pack_quality() -> None:
    fb = _high_quality_feedback()
    adj_scorer = FeedbackAdjustedContextScorer(fb)
    base_scorer = FallbackContextScorer()
    ref = _evidence_ref("ev-never-seen", staleness_status="valid")
    base_score = base_scorer.score_evidence_expansion([ref])[0].score
    adj_score = adj_scorer.score_evidence_expansion([ref])[0].score
    # With positive pack quality_score, unseen evidence should also receive a boost
    assert adj_score >= base_score


# ---------------------------------------------------------------------------
# FeedbackAdjustedContextScorer — summary usefulness
# ---------------------------------------------------------------------------


def test_feedback_scorer_usefulness_boosted_by_feedback() -> None:
    fb = _high_quality_feedback()
    adj_scorer = FeedbackAdjustedContextScorer(fb)
    base_scorer = FallbackContextScorer()
    s = _summary(facts=[_fact("fix failing test")])
    task = "fix failing test"
    base_score = base_scorer.score_summary_usefulness([s], task_text=task)[0].score
    adj_score = adj_scorer.score_summary_usefulness([s], task_text=task)[0].score
    assert adj_score >= base_score


def test_feedback_scorer_usefulness_stale_capped() -> None:
    fb = _high_quality_feedback()
    adj_scorer = FeedbackAdjustedContextScorer(fb)
    stale_s = _summary(facts=[_fact()] * 4, validity_status="stale")
    score = adj_scorer.score_summary_usefulness([stale_s])[0].score
    assert score <= STALE_MAX_SCORE


# ---------------------------------------------------------------------------
# FeedbackAdjustedContextScorer — staleness risk (never adjusted)
# ---------------------------------------------------------------------------


def test_staleness_risk_not_adjusted_by_positive_feedback() -> None:
    fb = _high_quality_feedback()
    adj_scorer = FeedbackAdjustedContextScorer(fb)
    base_scorer = FallbackContextScorer()
    for status in ("valid", "partial", "stale", "contradicted"):
        s = _summary(validity_status=status)
        base_risk = base_scorer.score_staleness_risk([s])[0].risk
        adj_risk = adj_scorer.score_staleness_risk([s])[0].risk
        assert adj_risk == pytest.approx(base_risk), f"staleness_risk changed for {status}"


def test_staleness_risk_stale_stays_high_regardless_of_feedback() -> None:
    fb = _high_quality_feedback()
    adj_scorer = FeedbackAdjustedContextScorer(fb)
    stale = _summary(validity_status="stale")
    risk = adj_scorer.score_staleness_risk([stale])[0].risk
    assert risk > 0.5


def test_staleness_risk_contradicted_stays_max() -> None:
    fb = _high_quality_feedback()
    adj_scorer = FeedbackAdjustedContextScorer(fb)
    contradicted = _summary(validity_status="contradicted")
    risk = adj_scorer.score_staleness_risk([contradicted])[0].risk
    assert risk == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Deterministic ranking improvement (no learned model)
# ---------------------------------------------------------------------------


def test_feedback_improves_ranking_of_valid_over_stale() -> None:
    """Feedback scorer ranks a valid-rich summary above stale-rich — deterministically."""
    fb = _high_quality_feedback()
    adj_scorer = FeedbackAdjustedContextScorer(fb)

    valid_rich = _summary("v", facts=[_fact()] * 3, validity_status="valid")
    stale_rich = _summary("s", facts=[_fact()] * 4, validity_status="stale")

    scores = {r.summary_id: r.score for r in adj_scorer.score_admission([valid_rich, stale_rich])}
    assert scores["v"] > scores["s"]


def test_feedback_ranking_is_deterministic() -> None:
    fb = _high_quality_feedback()
    adj_scorer = FeedbackAdjustedContextScorer(fb)
    s = _summary(facts=[_fact()])
    r1 = adj_scorer.score_admission([s])[0].score
    r2 = adj_scorer.score_admission([s])[0].score
    assert r1 == pytest.approx(r2)


# ---------------------------------------------------------------------------
# Eval hook integration
# ---------------------------------------------------------------------------


def test_eval_hook_called_for_feedback_scored_items() -> None:
    events: list[ScoringEvent] = []
    fb = _high_quality_feedback()
    scorer = FeedbackAdjustedContextScorer(fb, eval_hook=events.append)
    summaries = [_summary(f"sum-{i}", facts=[_fact()]) for i in range(3)]
    scorer.score_admission(summaries)
    assert len(events) == 3
    assert all(e.scorer_kind == "admission" for e in events)


def test_eval_hook_receives_adjusted_score() -> None:
    events: list[ScoringEvent] = []
    fb = _high_quality_feedback()
    scorer = FeedbackAdjustedContextScorer(fb, eval_hook=events.append)
    base_scorer = FallbackContextScorer()
    s = _summary(facts=[_fact()])
    base_score = base_scorer.score_admission([s])[0].score
    scorer.score_admission([s])
    assert events[0].score >= base_score


# ---------------------------------------------------------------------------
# Aggregate-safe features (no raw content)
# ---------------------------------------------------------------------------


def test_pack_feedback_contains_only_aggregate_fields() -> None:
    """PackFeedback must not store raw prompts, tool output, or user text."""
    fb = _high_quality_feedback()
    # Only structural/numeric fields exist
    assert hasattr(fb, "total_turns")
    assert hasattr(fb, "quality_turns")
    assert hasattr(fb, "adoption_count")
    assert hasattr(fb, "success_count")
    assert hasattr(fb, "quality_score")
    assert hasattr(fb, "evidence_feedback")
    # No raw text fields
    assert not hasattr(fb, "raw_stdout")
    assert not hasattr(fb, "prompt_text")
    assert not hasattr(fb, "tool_output")


def test_evidence_feedback_contains_only_aggregate_fields() -> None:
    records = [_record("adopted", "success", ["ev-001"])]
    fb = aggregate_anvil_feedback(records)
    ev = fb.evidence_feedback["ev-001"]
    assert isinstance(ev, EvidenceFeedback)
    assert hasattr(ev, "evidence_id")
    assert hasattr(ev, "expansion_count")
    assert hasattr(ev, "success_count")
    assert hasattr(ev, "quality_score")
