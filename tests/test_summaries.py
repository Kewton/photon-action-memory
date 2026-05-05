"""Tests for ActionSummaryBuilder, SummaryCanonicalizer, and SummaryStateUpdater."""

from __future__ import annotations

import pytest

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionChunk,
    ActionSummary,
)
from photon_action_memory.memory.summaries import (
    ActionSummaryBuilder,
    CanonicalizeResult,
    SummaryCanonicalizer,
    SummaryStateUpdater,
)

SCHEMA_V2 = DEFAULT_SCHEMA_VERSION_V2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chunk(
    *,
    chunk_id: str = "chunk_001",
    session_id: str = "sess_001",
    kind: str = "repo_search",
    summary: str = "Searched SessionStore.",
    outcome: str = "useful",
    event_ids: list[str] | None = None,
    repo_id: str | None = "repo_001",
    commit: str | None = "abc123",
) -> ActionChunk:
    return ActionChunk.model_validate(
        {
            "schema_version": SCHEMA_V2,
            "chunk_id": chunk_id,
            "session_id": session_id,
            "kind": kind,
            "summary": summary,
            "outcome": outcome,
            "event_ids": ["evt_001"] if event_ids is None else event_ids,
            "repo_id": repo_id,
            "commit": commit,
        }
    )


def _minimal_summary(
    *,
    summary_id: str = "sum_000",
    session_id: str = "sess_001",
    repo_id: str = "repo_001",
) -> ActionSummary:
    return ActionSummary.model_validate(
        {
            "schema_version": SCHEMA_V2,
            "summary_id": summary_id,
            "session_id": session_id,
            "repo_id": repo_id,
        }
    )


# ---------------------------------------------------------------------------
# ActionSummaryBuilder
# ---------------------------------------------------------------------------


class TestActionSummaryBuilder:
    def setup_method(self) -> None:
        self.builder = ActionSummaryBuilder()

    def test_build_returns_action_summary(self) -> None:
        summary = self.builder.build(_chunk())
        assert isinstance(summary, ActionSummary)
        assert summary.schema_version == SCHEMA_V2

    def test_build_propagates_session_and_repo(self) -> None:
        summary = self.builder.build(_chunk(session_id="sess_x", repo_id="repo_x"))
        assert summary.session_id == "sess_x"
        assert summary.repo_id == "repo_x"

    def test_build_source_chunk_ids(self) -> None:
        summary = self.builder.build(_chunk(chunk_id="chunk_017"))
        assert summary.source_chunk_ids == ["chunk_017"]

    def test_build_summary_level_is_chunk(self) -> None:
        summary = self.builder.build(_chunk())
        assert summary.summary_level == "chunk"

    def test_build_custom_summary_id(self) -> None:
        summary = self.builder.build(_chunk(), summary_id="sum_custom")
        assert summary.summary_id == "sum_custom"

    def test_build_auto_generates_deterministic_summary_id(self) -> None:
        s1 = self.builder.build(_chunk())
        s2 = self.builder.build(_chunk())
        assert s1.summary_id.startswith("sum-")
        assert s1.summary_id == s2.summary_id

    def test_build_auto_summary_id_changes_by_chunk_id(self) -> None:
        s1 = self.builder.build(_chunk(chunk_id="chunk_001"))
        s2 = self.builder.build(_chunk(chunk_id="chunk_002"))
        assert s1.summary_id != s2.summary_id

    # --- actions_done ---

    def test_actions_done_always_populated(self) -> None:
        for outcome in ("useful", "failed", "partial", "irrelevant", "unknown"):
            summary = self.builder.build(_chunk(outcome=outcome))
            assert len(summary.actions_done) == 1
            assert summary.actions_done[0].status == outcome

    def test_actions_done_carries_evidence_ids(self) -> None:
        summary = self.builder.build(_chunk(event_ids=["evt_041", "evt_042"]))
        assert summary.actions_done[0].evidence_ids == ["evt_041", "evt_042"]

    # --- facts ---

    def test_useful_chunk_produces_fact(self) -> None:
        summary = self.builder.build(_chunk(outcome="useful", event_ids=["evt_041"]))
        assert len(summary.facts) == 1
        assert summary.facts[0].evidence_ids == ["evt_041"]
        assert summary.facts[0].confidence == pytest.approx(0.9)

    def test_facts_require_evidence_ids(self) -> None:
        summary = self.builder.build(_chunk(outcome="useful", event_ids=[]))
        assert summary.facts == []

    def test_failed_chunk_produces_no_facts(self) -> None:
        summary = self.builder.build(_chunk(outcome="failed", event_ids=["evt_001"]))
        assert summary.facts == []

    def test_partial_chunk_produces_no_facts(self) -> None:
        summary = self.builder.build(_chunk(outcome="partial", event_ids=["evt_001"]))
        assert summary.facts == []

    def test_irrelevant_chunk_produces_no_facts(self) -> None:
        summary = self.builder.build(_chunk(outcome="irrelevant", event_ids=["evt_001"]))
        assert summary.facts == []

    def test_unknown_outcome_produces_no_facts(self) -> None:
        summary = self.builder.build(_chunk(outcome="unknown"))
        assert summary.facts == []

    # --- hypotheses ---

    def test_partial_chunk_produces_hypothesis(self) -> None:
        summary = self.builder.build(_chunk(outcome="partial", event_ids=["evt_001"]))
        assert len(summary.hypotheses) == 1
        assert summary.hypotheses[0].status == "open"
        assert summary.hypotheses[0].confidence == pytest.approx(0.5)
        assert summary.hypotheses[0].evidence_ids == ["evt_001"]

    def test_useful_chunk_produces_no_hypotheses(self) -> None:
        summary = self.builder.build(_chunk(outcome="useful"))
        assert summary.hypotheses == []

    def test_failed_chunk_produces_no_hypotheses(self) -> None:
        summary = self.builder.build(_chunk(outcome="failed"))
        assert summary.hypotheses == []

    # --- failed_attempts ---

    def test_failed_chunk_produces_failed_attempt(self) -> None:
        summary = self.builder.build(
            _chunk(outcome="failed", kind="test_verification", summary="cargo test failed.")
        )
        assert len(summary.failed_attempts) == 1
        fa = summary.failed_attempts[0]
        assert "test_verification" in fa.action
        assert fa.retry_policy == "avoid_until_files_changed"

    def test_failed_attempt_carries_evidence_ids(self) -> None:
        summary = self.builder.build(_chunk(outcome="failed", event_ids=["evt_052"]))
        assert summary.failed_attempts[0].evidence_ids == ["evt_052"]

    def test_useful_chunk_produces_no_failed_attempts(self) -> None:
        summary = self.builder.build(_chunk(outcome="useful"))
        assert summary.failed_attempts == []

    # --- avoid ---

    def test_irrelevant_chunk_produces_avoid_guidance(self) -> None:
        summary = self.builder.build(_chunk(outcome="irrelevant", event_ids=["evt_099"]))
        assert len(summary.avoid) == 1
        assert summary.avoid[0].reason == "action produced no useful result"
        assert summary.avoid[0].evidence_ids == ["evt_099"]

    def test_useful_chunk_produces_no_avoid(self) -> None:
        summary = self.builder.build(_chunk(outcome="useful"))
        assert summary.avoid == []

    def test_failed_chunk_produces_no_avoid(self) -> None:
        summary = self.builder.build(_chunk(outcome="failed"))
        assert summary.avoid == []

    # --- next_hints ---

    def test_failed_chunk_produces_inspect_hint(self) -> None:
        summary = self.builder.build(_chunk(outcome="failed"))
        assert len(summary.next_hints) == 1
        assert summary.next_hints[0].kind == "inspect"

    def test_useful_repo_search_produces_read_hint(self) -> None:
        summary = self.builder.build(_chunk(outcome="useful", kind="repo_search"))
        assert len(summary.next_hints) == 1
        assert summary.next_hints[0].kind == "read"

    def test_partial_repo_search_produces_read_hint(self) -> None:
        summary = self.builder.build(_chunk(outcome="partial", kind="repo_search"))
        assert len(summary.next_hints) == 1
        assert summary.next_hints[0].kind == "read"

    def test_useful_non_search_chunk_produces_no_hints(self) -> None:
        summary = self.builder.build(_chunk(outcome="useful", kind="file_inspection"))
        assert summary.next_hints == []

    # --- token_cost ---

    def test_token_cost_summary_tokens_ge_one(self) -> None:
        summary = self.builder.build(_chunk(summary="X"))
        assert summary.token_cost is not None
        assert summary.token_cost.estimated_summary_tokens >= 1

    def test_token_cost_raw_ge_summary(self) -> None:
        summary = self.builder.build(_chunk(event_ids=["evt_001", "evt_002"]))
        assert summary.token_cost is not None
        assert (
            summary.token_cost.estimated_raw_tokens >= summary.token_cost.estimated_summary_tokens
        )

    def test_token_cost_savings(self) -> None:
        summary = self.builder.build(_chunk(event_ids=["evt_001", "evt_002"]))
        tc = summary.token_cost
        assert tc is not None
        assert tc.tokens_saved_vs_raw == tc.estimated_raw_tokens - tc.estimated_summary_tokens

    def test_token_cost_with_no_events(self) -> None:
        summary = self.builder.build(_chunk(event_ids=[]))
        assert summary.token_cost is not None
        assert summary.token_cost.tokens_saved_vs_raw == 0

    # --- validity ---

    def test_built_summary_validity_is_valid(self) -> None:
        summary = self.builder.build(_chunk())
        assert summary.validity.status == "valid"

    # --- fact/hypothesis/failed separation invariant ---

    def test_failed_chunk_not_in_facts_not_in_hypotheses(self) -> None:
        summary = self.builder.build(_chunk(outcome="failed"))
        assert summary.facts == []
        assert summary.hypotheses == []
        assert len(summary.failed_attempts) == 1

    def test_useful_chunk_not_in_failed_not_in_hypotheses(self) -> None:
        summary = self.builder.build(_chunk(outcome="useful"))
        assert summary.failed_attempts == []
        assert summary.hypotheses == []
        assert len(summary.facts) == 1


# ---------------------------------------------------------------------------
# SummaryCanonicalizer
# ---------------------------------------------------------------------------


class TestSummaryCanonicalizer:
    def setup_method(self) -> None:
        self.canonicalizer = SummaryCanonicalizer()

    def _summary_with_facts(self, facts: list[dict[str, object]]) -> ActionSummary:
        return ActionSummary.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "summary_id": "sum_test",
                "facts": facts,
            }
        )

    def test_grounded_fact_kept(self) -> None:
        summary = self._summary_with_facts(
            [{"text": "Store is in store.rs.", "evidence_ids": ["evt_001"]}]
        )
        result = self.canonicalizer.canonicalize(summary)
        assert isinstance(result, CanonicalizeResult)
        assert result.removed_ungrounded_facts == 0
        assert len(result.summary.facts) == 1

    def test_ungrounded_fact_removed(self) -> None:
        summary = self._summary_with_facts([{"text": "Ungrounded claim.", "evidence_ids": []}])
        result = self.canonicalizer.canonicalize(summary)
        assert result.removed_ungrounded_facts == 1
        assert result.summary.facts == []
        assert len(result.warnings) == 1

    def test_mixed_facts_only_grounded_kept(self) -> None:
        summary = self._summary_with_facts(
            [
                {"text": "Grounded.", "evidence_ids": ["evt_001"]},
                {"text": "Ungrounded.", "evidence_ids": []},
            ]
        )
        result = self.canonicalizer.canonicalize(summary)
        assert result.removed_ungrounded_facts == 1
        assert len(result.summary.facts) == 1
        assert result.summary.facts[0].text == "Grounded."

    def test_validity_downgraded_when_facts_removed(self) -> None:
        summary = self._summary_with_facts([{"text": "Bad fact.", "evidence_ids": []}])
        result = self.canonicalizer.canonicalize(summary)
        assert result.summary.validity.status == "partial"
        assert result.summary.validity.reason is not None

    def test_validity_not_changed_for_already_non_valid(self) -> None:
        raw = ActionSummary.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "summary_id": "sum_test",
                "facts": [{"text": "Bad.", "evidence_ids": []}],
                "validity": {"status": "stale"},
            }
        )
        result = self.canonicalizer.canonicalize(raw)
        # validity was already non-valid; should not overwrite it
        assert result.summary.validity.status == "stale"

    def test_empty_summary_unchanged(self) -> None:
        summary = _minimal_summary()
        result = self.canonicalizer.canonicalize(summary)
        assert result.removed_ungrounded_facts == 0
        assert result.warnings == []
        assert result.summary.facts == []

    def test_warning_message_contains_fact_text_snippet(self) -> None:
        summary = self._summary_with_facts(
            [{"text": "This is a specific fact.", "evidence_ids": []}]
        )
        result = self.canonicalizer.canonicalize(summary)
        assert any("This is a specific fact." in w for w in result.warnings)

    def test_hypotheses_untouched(self) -> None:
        summary = ActionSummary.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "summary_id": "sum_test",
                "hypotheses": [
                    {
                        "text": "Maybe serde path.",
                        "evidence_ids": ["evt_052"],
                        "status": "open",
                    }
                ],
            }
        )
        result = self.canonicalizer.canonicalize(summary)
        assert len(result.summary.hypotheses) == 1
        assert result.summary.hypotheses[0].status == "open"


# ---------------------------------------------------------------------------
# SummaryStateUpdater
# ---------------------------------------------------------------------------


class TestSummaryStateUpdater:
    def setup_method(self) -> None:
        self.updater = SummaryStateUpdater()

    def test_update_returns_action_summary(self) -> None:
        prev = _minimal_summary()
        updated = self.updater.update(prev, _chunk())
        assert isinstance(updated, ActionSummary)
        assert updated.schema_version == SCHEMA_V2

    def test_update_appends_source_chunk_ids(self) -> None:
        prev = ActionSummary.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "summary_id": "sum_000",
                "source_chunk_ids": ["chunk_000"],
            }
        )
        updated = self.updater.update(prev, _chunk(chunk_id="chunk_001"))
        assert updated.source_chunk_ids == ["chunk_000", "chunk_001"]

    def test_update_appends_actions_done(self) -> None:
        prev = _minimal_summary()
        updated = self.updater.update(prev, _chunk())
        assert len(updated.actions_done) == 1

        updated2 = self.updater.update(updated, _chunk(chunk_id="chunk_002", outcome="failed"))
        assert len(updated2.actions_done) == 2

    def test_update_merges_facts_without_duplicates(self) -> None:
        prev = ActionSummary.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "summary_id": "sum_000",
                "facts": [{"text": "Store is in store.rs.", "evidence_ids": ["evt_000"]}],
            }
        )
        # chunk produces a different fact
        updated = self.updater.update(
            prev,
            _chunk(outcome="useful", summary="Test found in tests/.", event_ids=["evt_001"]),
        )
        assert len(updated.facts) == 2

    def test_update_deduplicates_facts_by_text(self) -> None:
        prev = ActionSummary.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "summary_id": "sum_000",
                "facts": [{"text": "Searched SessionStore.", "evidence_ids": ["evt_000"]}],
            }
        )
        # chunk produces the exact same fact text
        updated = self.updater.update(
            prev,
            _chunk(outcome="useful", summary="Searched SessionStore.", event_ids=["evt_001"]),
        )
        assert len(updated.facts) == 1

    def test_update_merges_hypotheses(self) -> None:
        prev = ActionSummary.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "summary_id": "sum_000",
                "hypotheses": [
                    {"text": "Maybe serde issue.", "evidence_ids": ["evt_010"], "status": "open"}
                ],
            }
        )
        updated = self.updater.update(
            prev,
            _chunk(outcome="partial", summary="Possible config mismatch.", event_ids=["evt_011"]),
        )
        assert len(updated.hypotheses) == 2

    def test_update_merges_failed_attempts(self) -> None:
        builder = ActionSummaryBuilder()
        prev_chunk = _chunk(outcome="failed", chunk_id="chunk_001", summary="cargo test failed.")
        prev = builder.build(prev_chunk)

        updated = self.updater.update(
            prev,
            _chunk(outcome="failed", chunk_id="chunk_002", summary="make build failed."),
        )
        assert len(updated.failed_attempts) == 2

    def test_update_deduplicates_failed_attempts(self) -> None:
        builder = ActionSummaryBuilder()
        prev_chunk = _chunk(
            outcome="failed",
            chunk_id="chunk_001",
            kind="test_verification",
            summary="cargo test failed.",
        )
        prev = builder.build(prev_chunk)

        updated = self.updater.update(
            prev,
            _chunk(
                outcome="failed",
                chunk_id="chunk_002",
                kind="test_verification",
                summary="cargo test failed.",  # same text -> same action key
            ),
        )
        assert len(updated.failed_attempts) == 1

    def test_update_merges_avoid_guidance(self) -> None:
        prev = ActionSummary.model_validate(
            {
                "schema_version": SCHEMA_V2,
                "summary_id": "sum_000",
                "avoid": [
                    {
                        "action": "repo_search: grep for X",
                        "reason": "already done",
                        "evidence_ids": ["evt_000"],
                    }
                ],
            }
        )
        updated = self.updater.update(
            prev,
            _chunk(outcome="irrelevant", kind="file_inspection", summary="read irrelevant file"),
        )
        assert len(updated.avoid) == 2

    def test_update_uses_newer_next_hints(self) -> None:
        builder = ActionSummaryBuilder()
        prev = builder.build(_chunk(outcome="useful", kind="repo_search"))
        assert prev.next_hints  # has hints from first chunk

        updated = self.updater.update(
            prev,
            _chunk(outcome="useful", kind="file_inspection", chunk_id="chunk_002"),
        )
        # file_inspection with useful outcome produces no hints in our heuristic
        assert updated.next_hints == []

    def test_update_adds_token_costs(self) -> None:
        builder = ActionSummaryBuilder()
        prev = builder.build(_chunk(event_ids=["evt_001"]))
        assert prev.token_cost is not None
        prev_raw = prev.token_cost.estimated_raw_tokens
        prev_sum = prev.token_cost.estimated_summary_tokens

        updated = self.updater.update(
            prev,
            _chunk(chunk_id="chunk_002", event_ids=["evt_002", "evt_003"]),
        )
        assert updated.token_cost is not None
        assert updated.token_cost.estimated_raw_tokens > prev_raw
        assert updated.token_cost.estimated_summary_tokens > prev_sum

    def test_update_failed_chunk_not_in_facts(self) -> None:
        prev = _minimal_summary()
        updated = self.updater.update(
            prev,
            _chunk(outcome="failed", event_ids=["evt_052"]),
        )
        assert updated.facts == []
        assert len(updated.failed_attempts) == 1

    def test_update_custom_summary_id(self) -> None:
        prev = _minimal_summary()
        updated = self.updater.update(prev, _chunk(), summary_id="sum_custom")
        assert updated.summary_id == "sum_custom"

    def test_incremental_multi_step_session(self) -> None:
        """Simulates a multi-turn session with mixed outcomes."""
        builder = ActionSummaryBuilder()

        # Turn 1: search -> useful
        s1 = builder.build(
            _chunk(
                chunk_id="chunk_001",
                kind="repo_search",
                summary="Found SessionStore in store.rs.",
                outcome="useful",
                event_ids=["evt_001"],
            )
        )
        assert len(s1.facts) == 1
        assert s1.failed_attempts == []

        # Turn 2: test -> failed
        s2 = self.updater.update(
            s1,
            _chunk(
                chunk_id="chunk_002",
                kind="test_verification",
                summary="cargo test session_persistence failed.",
                outcome="failed",
                event_ids=["evt_002"],
            ),
            summary_id="sum_002",
        )
        assert len(s2.facts) == 1
        assert len(s2.failed_attempts) == 1
        assert len(s2.source_chunk_ids) == 2
        assert len(s2.actions_done) == 2

        # Turn 3: file inspection -> partial
        s3 = self.updater.update(
            s2,
            _chunk(
                chunk_id="chunk_003",
                kind="file_inspection",
                summary="serde path may be related.",
                outcome="partial",
                event_ids=["evt_003"],
            ),
            summary_id="sum_003",
        )
        assert len(s3.facts) == 1
        assert len(s3.hypotheses) == 1
        assert len(s3.failed_attempts) == 1
        assert len(s3.source_chunk_ids) == 3
        assert s3.summary_id == "sum_003"

    def test_update_inherits_session_id_from_previous(self) -> None:
        prev = _minimal_summary(session_id="sess_inherited")
        updated = self.updater.update(prev, _chunk(session_id="sess_new"))
        assert updated.session_id == "sess_inherited"

    def test_update_default_summary_id_is_deterministic(self) -> None:
        prev = _minimal_summary(summary_id="sum_prev")
        chunk = _chunk(chunk_id="chunk_next")
        s1 = self.updater.update(prev, chunk)
        s2 = self.updater.update(prev, chunk)
        assert s1.summary_id.startswith("sum-")
        assert s1.summary_id == s2.summary_id

    def test_update_uses_chunk_commit(self) -> None:
        prev = _minimal_summary()
        updated = self.updater.update(prev, _chunk(commit="newcommit"))
        assert updated.commit == "newcommit"

    def test_update_validity_is_valid(self) -> None:
        prev = _minimal_summary()
        updated = self.updater.update(prev, _chunk())
        assert updated.validity.status == "valid"
