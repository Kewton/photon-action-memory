"""Issue #121 — ActionMemoryPhotonScorer boundary + deterministic fallback."""

from __future__ import annotations

from pathlib import Path

from photon_action_memory.models.photon_scorer import (
    DETERMINISTIC_MODEL_VERSION,
    ActionMemoryScoreResult,
    DeterministicActionMemoryScorer,
    EvidenceCandidate,
    FailedAttemptCandidate,
    NextHintCandidate,
    SummaryCandidate,
    make_action_memory_scorer,
)


def _score(
    scorer: DeterministicActionMemoryScorer,
    *,
    task_text: str = "fix SessionStore retrieval bug",
    summaries: list[SummaryCandidate] | None = None,
    evidence: list[EvidenceCandidate] | None = None,
    next_hints: list[NextHintCandidate] | None = None,
    failed: list[FailedAttemptCandidate] | None = None,
) -> ActionMemoryScoreResult:
    return scorer.score(
        request_id="req-123",
        repo_id="repo-001",
        task_text=task_text,
        candidate_summaries=summaries or [],
        candidate_evidence=evidence or [],
        candidate_next_hints=next_hints or [],
        candidate_failed_attempts=failed or [],
    )


class TestDeterministicScorer:
    def test_summary_score_higher_when_overlap_is_higher(self) -> None:
        scorer = DeterministicActionMemoryScorer()
        result = _score(
            scorer,
            summaries=[
                SummaryCandidate(
                    summary_id="sum_match",
                    text="SessionStore retrieval bug fix attempt",
                    evidence_ids=("evt_1",),
                ),
                SummaryCandidate(
                    summary_id="sum_noise",
                    text="unrelated documentation update",
                ),
            ],
        )
        assert len(result.summary_scores) == 2
        match_score = next(s for s in result.summary_scores if s.summary_id == "sum_match")
        noise_score = next(s for s in result.summary_scores if s.summary_id == "sum_noise")
        assert match_score.score > noise_score.score

    def test_evidence_score_for_overlap(self) -> None:
        scorer = DeterministicActionMemoryScorer()
        result = _score(
            scorer,
            evidence=[
                EvidenceCandidate(evidence_id="evt_1", text="SessionStore retrieval bug"),
                EvidenceCandidate(evidence_id="evt_2", text="random hello world"),
            ],
        )
        ev1 = next(s for s in result.evidence_scores if s.evidence_id == "evt_1")
        ev2 = next(s for s in result.evidence_scores if s.evidence_id == "evt_2")
        assert ev1.score > ev2.score

    def test_next_hint_and_failed_attempt_scores_present(self) -> None:
        scorer = DeterministicActionMemoryScorer()
        result = _score(
            scorer,
            next_hints=[
                NextHintCandidate(
                    index=0,
                    kind="inspect",
                    reason="check SessionStore",
                    target=None,
                ),
            ],
            failed=[
                FailedAttemptCandidate(
                    index=0,
                    action="rm SessionStore",
                    outcome="permission denied",
                ),
            ],
        )
        assert result.next_hint_scores[0].index == 0
        assert result.failure_similarity[0].index == 0

    def test_model_version_label(self) -> None:
        result = _score(DeterministicActionMemoryScorer())
        assert result.model_version == DETERMINISTIC_MODEL_VERSION
        assert result.drift_score is None

    def test_warnings_propagated_when_set(self) -> None:
        result = _score(DeterministicActionMemoryScorer(warnings=("photon_unavailable",)))
        assert result.warnings == ("photon_unavailable",)


class TestFactory:
    def test_no_checkpoint_env_returns_deterministic(self) -> None:
        scorer = make_action_memory_scorer(env={})
        assert isinstance(scorer, DeterministicActionMemoryScorer)
        assert scorer.warnings == ()

    def test_invalid_checkpoint_env_falls_back_with_warning(self, tmp_path: Path) -> None:
        bogus = tmp_path / "missing-checkpoint.json"
        scorer = make_action_memory_scorer(
            env={"PHOTON_ACTION_MEMORY_CHECKPOINT": str(bogus)},
        )
        assert isinstance(scorer, DeterministicActionMemoryScorer)
        assert scorer.warnings == ("photon_unavailable",)

    def test_factory_does_not_raise(self) -> None:
        # Even with garbage env, no exception escapes.
        scorer = make_action_memory_scorer(
            env={"PHOTON_ACTION_MEMORY_CHECKPOINT": "/path/that/does/not/exist"},
        )
        assert isinstance(scorer, DeterministicActionMemoryScorer)
