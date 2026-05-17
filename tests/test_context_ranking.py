"""Issue #126 — /v1/context/pack ranking mode tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ContextPack,
    ContextPackItem,
    ContextPackWarning,
    TokenBudget,
)
from photon_action_memory.models.photon_scorer import (
    ActionMemoryScoreResult,
    DeterministicActionMemoryScorer,
    ScoredSummary,
)
from photon_action_memory.ranking.context_ranking import (
    DEFAULT_PHOTON_WEIGHT,
    apply_ranking_mode,
    resolve_canary_ratio,
    resolve_photon_weight,
    resolve_ranking_mode,
)


@dataclass
class _StaticScorer:
    """Deterministic stand-in that lets the test pick per-id scores."""

    scores: dict[str, float]
    model_version: str = "static-test-model"

    def score(self, **kwargs: Any) -> ActionMemoryScoreResult:
        candidates = kwargs.get("candidate_summaries", ())
        return ActionMemoryScoreResult(
            summary_scores=tuple(
                ScoredSummary(
                    summary_id=cand.summary_id,
                    score=self.scores.get(cand.summary_id, 0.0),
                    reason="static",
                )
                for cand in candidates
            ),
            model_version=self.model_version,
        )


def _pack(item_ids: list[str]) -> ContextPack:
    return ContextPack(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        request_id="req-1",
        session_id=None,
        repo_id=None,
        mode="summary_only",
        items=[
            ContextPackItem(kind="action_summary", id=item_id, text=f"render-{item_id}")
            for item_id in item_ids
        ],
        omitted=[],
        warnings=[ContextPackWarning(kind="prior", message="pre-existing")],
        token_budget=TokenBudget(max_tokens=100, estimated_tokens=10, tokens_saved_vs_raw=0),
    )


def test_resolve_ranking_mode_defaults_to_deterministic() -> None:
    assert resolve_ranking_mode({}) == "deterministic"
    assert resolve_ranking_mode({"PHOTON_CONTEXT_PACK_RANKING": "garbage"}) == "deterministic"


def test_resolve_ranking_mode_accepts_all_modes() -> None:
    for mode in ("deterministic", "photon_shadow", "photon_canary", "photon"):
        assert resolve_ranking_mode({"PHOTON_CONTEXT_PACK_RANKING": mode}) == mode


def test_resolve_photon_weight_clamps_to_unit_interval() -> None:
    assert resolve_photon_weight({"PHOTON_CONTEXT_PACK_PHOTON_WEIGHT": "0.7"}) == 0.7
    assert resolve_photon_weight({"PHOTON_CONTEXT_PACK_PHOTON_WEIGHT": "1.7"}) == 1.0
    assert resolve_photon_weight({"PHOTON_CONTEXT_PACK_PHOTON_WEIGHT": "-1"}) == 0.0
    assert resolve_photon_weight({}) == DEFAULT_PHOTON_WEIGHT


def test_resolve_canary_ratio_clamps_to_unit_interval() -> None:
    assert resolve_canary_ratio({"PHOTON_CONTEXT_PACK_CANARY_RATIO": "0.25"}) == 0.25
    assert resolve_canary_ratio({"PHOTON_CONTEXT_PACK_CANARY_RATIO": "10"}) == 1.0


def test_deterministic_mode_short_circuits_without_scorer() -> None:
    pack = _pack(["sum-a", "sum-b"])
    result = apply_ranking_mode(
        pack,
        mode="deterministic",
        scorer=None,
        task_text="task",
        request_id="req-1",
        repo_id=None,
    )
    assert result.applied_mode == "deterministic"
    assert result.pack is pack


def test_missing_scorer_falls_back_with_warning() -> None:
    pack = _pack(["sum-a", "sum-b"])
    result = apply_ranking_mode(
        pack,
        mode="photon",
        scorer=None,
        task_text="task",
        request_id="req-1",
        repo_id=None,
    )
    assert result.applied_mode == "deterministic"
    assert result.fallback_reason == "scorer_unavailable"
    assert any(w.kind == "ranking_mode_fallback" for w in result.pack.warnings)


def test_photon_unavailable_warning_triggers_fallback() -> None:
    pack = _pack(["sum-a", "sum-b"])
    scorer = DeterministicActionMemoryScorer(warnings=("photon_unavailable",))
    result = apply_ranking_mode(
        pack,
        mode="photon",
        scorer=scorer,
        task_text="task",
        request_id="req-1",
        repo_id=None,
    )
    assert result.applied_mode == "deterministic"
    assert result.fallback_reason == "photon_unavailable"


def test_photon_mode_reorders_items_by_score() -> None:
    pack = _pack(["sum-a", "sum-b", "sum-c"])
    # Static scorer ranks c > b > a, but a was first deterministically.
    scorer = _StaticScorer(scores={"sum-a": 0.1, "sum-b": 0.5, "sum-c": 0.9})
    result = apply_ranking_mode(
        pack,
        mode="photon",
        scorer=scorer,
        task_text="task",
        request_id="req-1",
        repo_id=None,
        photon_weight=0.9,
    )
    assert result.applied_mode == "photon"
    ordered_ids = [item.id for item in result.pack.items]
    assert ordered_ids[0] == "sum-c"
    assert "sum-a" in ordered_ids
    assert "sum-b" in ordered_ids


def test_shadow_mode_keeps_order_and_emits_report() -> None:
    pack = _pack(["sum-a", "sum-b"])
    scorer = _StaticScorer(scores={"sum-a": 0.1, "sum-b": 0.9})
    result = apply_ranking_mode(
        pack,
        mode="photon_shadow",
        scorer=scorer,
        task_text="task",
        request_id="req-1",
        repo_id=None,
    )
    assert result.applied_mode == "photon_shadow"
    ordered_ids = [item.id for item in result.pack.items]
    assert ordered_ids == ["sum-a", "sum-b"]
    reports = [w for w in result.pack.warnings if w.kind == "ranking_report"]
    assert reports, "expected a ranking_report warning in shadow mode"
    assert "sum-a" in reports[0].message and "sum-b" in reports[0].message


def test_photon_does_not_re_admit_omitted_items() -> None:
    pack = _pack(["sum-a", "sum-b"])
    # Even with a huge score, the unadmitted item shouldn't appear because
    # apply_ranking_mode only sees pack.items.
    scorer = _StaticScorer(scores={"sum-a": 0.1, "sum-b": 0.9, "sum-evil": 1.0})
    result = apply_ranking_mode(
        pack,
        mode="photon",
        scorer=scorer,
        task_text="task",
        request_id="req-1",
        repo_id=None,
    )
    ids = {item.id for item in result.pack.items}
    assert "sum-evil" not in ids


def test_canary_mode_uses_shadow_for_excluded_requests() -> None:
    pack = _pack(["sum-a", "sum-b"])
    scorer = _StaticScorer(scores={"sum-a": 0.1, "sum-b": 0.9})
    # Ratio 0 means no request is in the canary bucket.
    result = apply_ranking_mode(
        pack,
        mode="photon_canary",
        scorer=scorer,
        task_text="task",
        request_id="req-out",
        repo_id=None,
        canary_ratio=0.0,
    )
    assert result.applied_mode == "photon_shadow"
    # Order preserved.
    assert [item.id for item in result.pack.items] == ["sum-a", "sum-b"]


def test_canary_mode_applies_when_request_in_bucket() -> None:
    pack = _pack(["sum-a", "sum-b"])
    scorer = _StaticScorer(scores={"sum-a": 0.1, "sum-b": 0.9})
    # Ratio 1 means every request is in the bucket.
    result = apply_ranking_mode(
        pack,
        mode="photon_canary",
        scorer=scorer,
        task_text="task",
        request_id="req-in",
        repo_id=None,
        canary_ratio=1.0,
        photon_weight=0.9,
    )
    assert result.applied_mode == "photon_canary"
    assert result.pack.items[0].id == "sum-b"


def test_empty_pack_short_circuits() -> None:
    pack = _pack([])
    scorer = _StaticScorer(scores={})
    result = apply_ranking_mode(
        pack,
        mode="photon",
        scorer=scorer,
        task_text="task",
        request_id="req-1",
        repo_id=None,
    )
    assert result.applied_mode == "deterministic"
    assert result.pack is pack


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
