"""Unit tests for syntax-based contradiction detection (Issue #110)."""

from __future__ import annotations

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionDone,
    ActionSummary,
    AvoidGuidance,
    Fact,
    FailedAttempt,
    NextHint,
    Validity,
)
from photon_action_memory.governance.contradiction import (
    ContradictionPair,
    detect_contradictions,
)


def _summary(
    summary_id: str,
    *,
    repo_id: str | None = "repo-x",
    task_signature: str | None = "fix-bug",
    facts: list[Fact] | None = None,
    avoid: list[AvoidGuidance] | None = None,
    actions_done: list[ActionDone] | None = None,
    next_hints: list[NextHint] | None = None,
    failed_attempts: list[FailedAttempt] | None = None,
) -> ActionSummary:
    return ActionSummary(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        summary_id=summary_id,
        repo_id=repo_id,
        task_signature=task_signature,
        facts=facts or [],
        avoid=avoid or [],
        actions_done=actions_done or [],
        next_hints=next_hints or [],
        failed_attempts=failed_attempts or [],
        validity=Validity(status="valid"),
    )


# 1. Empty input
def test_detect_contradictions_with_no_summaries_returns_empty() -> None:
    assert detect_contradictions([]) == []


# 2. Single summary
def test_detect_contradictions_with_single_summary_returns_empty() -> None:
    only = _summary(
        "only-1",
        avoid=[AvoidGuidance(action="rm -rf /", reason="dangerous")],
    )
    assert detect_contradictions([only]) == []


# 3. avoid vs actions_done
def test_detect_avoid_vs_actions_done_conflict() -> None:
    a = _summary(
        "avoid-rebase",
        avoid=[AvoidGuidance(action="git rebase main", reason="protected branch")],
    )
    b = _summary(
        "do-rebase",
        actions_done=[
            ActionDone(
                kind="run",
                command="git rebase main",
                outcome="ok",
                status="completed",
            )
        ],
    )
    pairs = detect_contradictions([a, b])
    kinds = {pair.kind for pair in pairs}
    assert "avoid_vs_action" in kinds


# 4. avoid vs unrelated actions_done — no conflict
def test_avoid_vs_unrelated_action_does_not_flag() -> None:
    a = _summary(
        "avoid-rebase",
        avoid=[AvoidGuidance(action="git rebase main", reason="protected branch")],
    )
    b = _summary(
        "run-tests",
        actions_done=[
            ActionDone(kind="run", command="pytest -v", outcome="ok", status="completed")
        ],
    )
    assert detect_contradictions([a, b]) == []


# 5. avoid vs avoid with opposite polarity
def test_avoid_polarity_conflict_detected() -> None:
    a = _summary(
        "avoid-foo-1",
        avoid=[AvoidGuidance(action="use foo bar", reason="do not use foo, use bar")],
    )
    b = _summary(
        "avoid-foo-2",
        avoid=[AvoidGuidance(action="use foo bar", reason="always use foo")],
    )
    pairs = detect_contradictions([a, b])
    kinds = {pair.kind for pair in pairs}
    assert "avoid_polarity_conflict" in kinds


# 6. avoid vs avoid with matching polarity — no conflict
def test_avoid_same_polarity_does_not_flag() -> None:
    a = _summary(
        "avoid-foo-1",
        avoid=[AvoidGuidance(action="use foo bar", reason="do not use foo")],
    )
    b = _summary(
        "avoid-foo-2",
        avoid=[AvoidGuidance(action="use foo bar", reason="never use foo here")],
    )
    pairs = detect_contradictions([a, b])
    assert all(pair.kind != "avoid_polarity_conflict" for pair in pairs)


# 7. fact negation in English
def test_fact_negation_english() -> None:
    a = _summary(
        "fact-pos",
        facts=[Fact(text="the cache is enabled by default", evidence_ids=["e1"])],
    )
    b = _summary(
        "fact-neg",
        facts=[Fact(text="the cache is not enabled by default", evidence_ids=["e2"])],
    )
    pairs = detect_contradictions([a, b])
    kinds = {pair.kind for pair in pairs}
    assert "fact_negation" in kinds


# 8. fact negation in Japanese
def test_fact_negation_japanese() -> None:
    a = _summary(
        "fact-jp-pos",
        facts=[Fact(text="このAPIは認証を必要とする", evidence_ids=["e1"])],
    )
    b = _summary(
        "fact-jp-neg",
        facts=[Fact(text="このAPIは認証を必要としない", evidence_ids=["e2"])],
    )
    pairs = detect_contradictions([a, b])
    kinds = {pair.kind for pair in pairs}
    assert "fact_negation" in kinds


# 9. overlapping facts but no negation
def test_fact_overlap_without_negation_does_not_flag() -> None:
    a = _summary(
        "fact-1",
        facts=[Fact(text="the build runs in five minutes", evidence_ids=["e1"])],
    )
    b = _summary(
        "fact-2",
        facts=[Fact(text="the build runs in five minutes locally", evidence_ids=["e2"])],
    )
    pairs = detect_contradictions([a, b])
    assert all(pair.kind != "fact_negation" for pair in pairs)


# 10. next_hint enable vs disable
def test_next_hint_opposite_verb_conflict() -> None:
    a = _summary(
        "hint-enable",
        next_hints=[
            NextHint(kind="enable", target="experimental_async_runtime", reason="needed")
        ],
    )
    b = _summary(
        "hint-disable",
        next_hints=[
            NextHint(
                kind="disable",
                target="experimental_async_runtime",
                reason="unstable",
            )
        ],
    )
    pairs = detect_contradictions([a, b])
    kinds = {pair.kind for pair in pairs}
    assert "next_hint_conflict" in kinds


# 11. next_hint synonymous verbs
def test_next_hint_same_verb_does_not_flag() -> None:
    a = _summary(
        "hint-enable-1",
        next_hints=[
            NextHint(kind="enable", target="cache_module", reason="speed")
        ],
    )
    b = _summary(
        "hint-enable-2",
        next_hints=[
            NextHint(kind="enable", target="cache_module", reason="for tests")
        ],
    )
    pairs = detect_contradictions([a, b])
    assert all(pair.kind != "next_hint_conflict" for pair in pairs)


# 12. failed_attempt vs next_hint
def test_failed_attempt_versus_next_hint_conflict() -> None:
    a = _summary(
        "fail-rebase",
        failed_attempts=[
            FailedAttempt(action="git rebase main with conflicts", outcome="conflict")
        ],
    )
    b = _summary(
        "hint-rebase",
        next_hints=[
            NextHint(kind="run", target="git rebase main with conflicts", reason="retry")
        ],
    )
    pairs = detect_contradictions([a, b])
    kinds = {pair.kind for pair in pairs}
    assert "failed_attempt_vs_next_hint" in kinds


# 13. different repo_id
def test_different_repo_ids_are_not_paired() -> None:
    a = _summary(
        "avoid-rebase",
        repo_id="repo-x",
        avoid=[AvoidGuidance(action="git rebase main", reason="protected")],
    )
    b = _summary(
        "do-rebase",
        repo_id="repo-y",
        actions_done=[
            ActionDone(kind="run", command="git rebase main", outcome="ok", status="completed")
        ],
    )
    assert detect_contradictions([a, b]) == []


# 14. different task_signature
def test_different_task_signatures_are_not_paired() -> None:
    a = _summary(
        "avoid-rebase",
        task_signature="task-1",
        avoid=[AvoidGuidance(action="git rebase main", reason="protected")],
    )
    b = _summary(
        "do-rebase",
        task_signature="task-2",
        actions_done=[
            ActionDone(kind="run", command="git rebase main", outcome="ok", status="completed")
        ],
    )
    assert detect_contradictions([a, b]) == []


# 15. result is deterministic and dedup'd
def test_pair_dedup_stable_keys() -> None:
    a = _summary(
        "avoid-rebase",
        avoid=[AvoidGuidance(action="git rebase main", reason="protected")],
    )
    b = _summary(
        "do-rebase",
        actions_done=[
            ActionDone(kind="run", command="git rebase main", outcome="ok", status="completed"),
            ActionDone(kind="run", command="git rebase main", outcome="ok", status="completed"),
        ],
    )
    pairs = detect_contradictions([a, b])
    keys = [(pair.summary_a_id, pair.summary_b_id, pair.kind, pair.evidence) for pair in pairs]
    assert len(keys) == len(set(keys))


def test_contradiction_pair_to_dict_round_trip() -> None:
    pair = ContradictionPair(
        summary_a_id="a",
        summary_b_id="b",
        kind="avoid_vs_action",
        evidence="example",
    )
    assert pair.to_dict() == {
        "summary_a_id": "a",
        "summary_b_id": "b",
        "kind": "avoid_vs_action",
        "evidence": "example",
    }
