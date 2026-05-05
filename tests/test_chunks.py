"""Tests for ActionChunker."""

from __future__ import annotations

import pytest

from photon_action_memory.api.schema_v2 import ActionChunk
from photon_action_memory.memory.chunks import ActionChunker
from photon_action_memory.memory.sanitizer import SanitizedPayload
from photon_action_memory.memory.store import StoredEvent


def _make_event(
    event_id: str = "evt-001",
    session_id: str = "session-001",
    turn_id: str = "turn-001",
    repo_id: str = "repo-001",
    timestamp: str = "2024-01-01T00:00:00+00:00",
    event_type: str = "file_read",
    payload: SanitizedPayload | None = None,
) -> StoredEvent:
    return StoredEvent(
        schema_version="action-memory.v1",
        event_id=event_id,
        session_id=session_id,
        turn_id=turn_id,
        repo_id=repo_id,
        timestamp=timestamp,
        event_type=event_type,
        payload=payload if payload is not None else {"redaction_status": "clean"},
    )


class TestActionChunkerBasic:
    def test_empty_input_returns_empty_list(self) -> None:
        assert ActionChunker().chunk([]) == []

    def test_single_event_produces_one_chunk(self) -> None:
        chunks = ActionChunker().chunk([_make_event()])
        assert len(chunks) == 1
        assert isinstance(chunks[0], ActionChunk)

    def test_event_ids_preserved(self) -> None:
        events = [_make_event(event_id="e1"), _make_event(event_id="e2")]
        chunks = ActionChunker().chunk(events)
        assert len(chunks) == 1
        assert set(chunks[0].event_ids) == {"e1", "e2"}

    def test_schema_version_is_v2(self) -> None:
        chunks = ActionChunker().chunk([_make_event()])
        assert chunks[0].schema_version == "action-memory.v0.2"

    def test_all_event_ids_present_in_order(self) -> None:
        events = [
            _make_event(event_id="e1"),
            _make_event(event_id="e2"),
            _make_event(event_id="e3"),
        ]
        chunks = ActionChunker().chunk(events)
        assert chunks[0].event_ids == ["e1", "e2", "e3"]


class TestActionChunkerGrouping:
    def test_same_turn_grouped_as_one_chunk(self) -> None:
        events = [
            _make_event(event_id="e1", turn_id="t1"),
            _make_event(event_id="e2", turn_id="t1"),
            _make_event(event_id="e3", turn_id="t1"),
        ]
        chunks = ActionChunker().chunk(events)
        assert len(chunks) == 1
        assert len(chunks[0].event_ids) == 3

    def test_different_turns_produce_separate_chunks(self) -> None:
        events = [
            _make_event(event_id="e1", turn_id="t1"),
            _make_event(event_id="e2", turn_id="t2"),
        ]
        chunks = ActionChunker().chunk(events)
        assert len(chunks) == 2

    def test_chunk_order_follows_first_seen_turn(self) -> None:
        events = [
            _make_event(event_id="e1", turn_id="t1"),
            _make_event(event_id="e2", turn_id="t2"),
            _make_event(event_id="e3", turn_id="t1"),
        ]
        chunks = ActionChunker().chunk(events)
        assert chunks[0].turn_id == "t1"
        assert chunks[1].turn_id == "t2"

    def test_three_turns_produce_three_chunks(self) -> None:
        events = [_make_event(event_id=f"e{i}", turn_id=f"t{i}") for i in range(3)]
        chunks = ActionChunker().chunk(events)
        assert len(chunks) == 3

    def test_different_sessions_produce_separate_chunks(self) -> None:
        events = [
            _make_event(event_id="e1", session_id="s1", turn_id="t1"),
            _make_event(event_id="e2", session_id="s2", turn_id="t1"),
        ]
        chunks = ActionChunker().chunk(events)
        assert len(chunks) == 2


class TestActionChunkerDeterminism:
    def test_same_events_produce_same_chunk_id(self) -> None:
        events = [_make_event(event_id="e1"), _make_event(event_id="e2")]
        chunker = ActionChunker()
        id_a = chunker.chunk(events)[0].chunk_id
        id_b = chunker.chunk(events)[0].chunk_id
        assert id_a == id_b

    def test_chunk_id_is_order_independent(self) -> None:
        events_ab = [_make_event(event_id="eA"), _make_event(event_id="eB")]
        events_ba = [_make_event(event_id="eB"), _make_event(event_id="eA")]
        chunker = ActionChunker()
        assert chunker.chunk_one(events_ab).chunk_id == chunker.chunk_one(events_ba).chunk_id

    def test_different_event_ids_produce_different_chunk_ids(self) -> None:
        chunker = ActionChunker()
        id_a = chunker.chunk_one([_make_event(event_id="eA")]).chunk_id
        id_b = chunker.chunk_one([_make_event(event_id="eB")]).chunk_id
        assert id_a != id_b

    def test_chunk_id_starts_with_chunk_prefix(self) -> None:
        chunk = ActionChunker().chunk_one([_make_event()])
        assert chunk.chunk_id.startswith("chunk-")


class TestActionChunkerKindInference:
    @pytest.mark.parametrize(
        ("event_type", "expected_kind"),
        [
            ("file_read", "file_inspection"),
            ("file_write", "edit_attempt"),
            ("file_edit", "edit_attempt"),
            ("file_create", "edit_attempt"),
            ("file_delete", "edit_attempt"),
            ("search", "repo_search"),
            ("grep", "repo_search"),
            ("repo_search", "repo_search"),
            ("test_run", "test_verification"),
            ("test_result", "test_verification"),
            ("edit", "edit_attempt"),
            ("answer", "answer_prep"),
            ("bash", "other"),
            ("failure", "failure_reproduction"),
            ("error", "failure_reproduction"),
        ],
    )
    def test_event_type_mapped_to_kind(self, event_type: str, expected_kind: str) -> None:
        chunk = ActionChunker().chunk_one([_make_event(event_type=event_type)])
        assert chunk.kind == expected_kind

    def test_unknown_event_type_maps_to_other(self) -> None:
        chunk = ActionChunker().chunk_one([_make_event(event_type="unknown_xyz")])
        assert chunk.kind == "other"

    def test_majority_kind_wins(self) -> None:
        events = [
            _make_event(event_id="e1", event_type="file_read"),
            _make_event(event_id="e2", event_type="file_read"),
            _make_event(event_id="e3", event_type="search"),
        ]
        assert ActionChunker().chunk_one(events).kind == "file_inspection"

    def test_case_insensitive_event_type(self) -> None:
        chunk = ActionChunker().chunk_one([_make_event(event_type="FILE_READ")])
        assert chunk.kind == "file_inspection"


class TestActionChunkerOutcome:
    def test_default_outcome_is_unknown(self) -> None:
        assert ActionChunker().chunk_one([_make_event()]).outcome == "unknown"

    def test_outcome_from_payload(self) -> None:
        events = [_make_event(payload={"outcome": "useful", "redaction_status": "clean"})]
        assert ActionChunker().chunk_one(events).outcome == "useful"

    def test_outcome_partial_from_payload(self) -> None:
        events = [_make_event(payload={"outcome": "partial", "redaction_status": "clean"})]
        assert ActionChunker().chunk_one(events).outcome == "partial"

    def test_status_success_maps_to_useful(self) -> None:
        events = [_make_event(payload={"status": "success", "redaction_status": "clean"})]
        assert ActionChunker().chunk_one(events).outcome == "useful"

    def test_status_passed_maps_to_useful(self) -> None:
        events = [_make_event(payload={"status": "passed", "redaction_status": "clean"})]
        assert ActionChunker().chunk_one(events).outcome == "useful"

    def test_status_failed_maps_to_failed(self) -> None:
        events = [_make_event(payload={"status": "failed", "redaction_status": "clean"})]
        assert ActionChunker().chunk_one(events).outcome == "failed"

    def test_status_error_maps_to_failed(self) -> None:
        events = [_make_event(payload={"status": "error", "redaction_status": "clean"})]
        assert ActionChunker().chunk_one(events).outcome == "failed"

    def test_last_event_outcome_takes_precedence(self) -> None:
        events = [
            _make_event(event_id="e1", payload={"outcome": "failed", "redaction_status": "clean"}),
            _make_event(event_id="e2", payload={"outcome": "useful", "redaction_status": "clean"}),
        ]
        assert ActionChunker().chunk_one(events).outcome == "useful"

    def test_invalid_outcome_in_payload_falls_back_to_unknown(self) -> None:
        events = [_make_event(payload={"outcome": "bogus_value", "redaction_status": "clean"})]
        assert ActionChunker().chunk_one(events).outcome == "unknown"


class TestActionChunkerRisk:
    def test_no_risk_info_returns_none_for_low_risk_kind(self) -> None:
        events = [_make_event(event_type="search")]
        assert ActionChunker().chunk_one(events).risk is None

    def test_risk_from_payload(self) -> None:
        events = [_make_event(payload={"risk": "high", "redaction_status": "clean"})]
        assert ActionChunker().chunk_one(events).risk == "high"

    def test_risk_low_from_payload(self) -> None:
        events = [_make_event(payload={"risk": "low", "redaction_status": "clean"})]
        assert ActionChunker().chunk_one(events).risk == "low"

    def test_edit_kind_infers_medium_risk(self) -> None:
        events = [_make_event(event_type="edit")]
        assert ActionChunker().chunk_one(events).risk == "medium"

    def test_failure_kind_infers_medium_risk(self) -> None:
        events = [_make_event(event_type="failure")]
        assert ActionChunker().chunk_one(events).risk == "medium"

    def test_payload_risk_takes_precedence_over_inferred(self) -> None:
        events = [
            _make_event(event_type="edit", payload={"risk": "low", "redaction_status": "clean"})
        ]
        assert ActionChunker().chunk_one(events).risk == "low"

    def test_invalid_risk_in_payload_falls_back_to_inferred(self) -> None:
        events = [
            _make_event(event_type="edit", payload={"risk": "extreme", "redaction_status": "clean"})
        ]
        assert ActionChunker().chunk_one(events).risk == "medium"


class TestActionChunkerFields:
    def test_session_id_propagated(self) -> None:
        chunk = ActionChunker().chunk_one([_make_event(session_id="sess-XYZ")])
        assert chunk.session_id == "sess-XYZ"

    def test_turn_id_propagated(self) -> None:
        chunk = ActionChunker().chunk_one([_make_event(turn_id="turn-42")])
        assert chunk.turn_id == "turn-42"

    def test_repo_id_propagated(self) -> None:
        chunk = ActionChunker().chunk_one([_make_event(repo_id="repo-ABC")])
        assert chunk.repo_id == "repo-ABC"

    def test_timestamps_propagated(self) -> None:
        events = [
            _make_event(event_id="e1", timestamp="2024-01-01T10:00:00+00:00"),
            _make_event(event_id="e2", timestamp="2024-01-01T11:00:00+00:00"),
        ]
        chunk = ActionChunker().chunk_one(events)
        assert chunk.started_at == "2024-01-01T10:00:00+00:00"
        assert chunk.ended_at == "2024-01-01T11:00:00+00:00"

    def test_single_event_started_equals_ended(self) -> None:
        chunk = ActionChunker().chunk_one([_make_event(timestamp="2024-01-01T00:00:00+00:00")])
        assert chunk.started_at == chunk.ended_at

    def test_commit_from_payload(self) -> None:
        events = [_make_event(payload={"commit": "abc123def", "redaction_status": "clean"})]
        assert ActionChunker().chunk_one(events).commit == "abc123def"

    def test_last_event_commit_wins(self) -> None:
        events = [
            _make_event(event_id="e1", payload={"commit": "old-sha", "redaction_status": "clean"}),
            _make_event(event_id="e2", payload={"commit": "new-sha", "redaction_status": "clean"}),
        ]
        assert ActionChunker().chunk_one(events).commit == "new-sha"

    def test_no_commit_in_payload_is_none(self) -> None:
        assert ActionChunker().chunk_one([_make_event()]).commit is None

    def test_summary_contains_kind(self) -> None:
        chunk = ActionChunker().chunk_one([_make_event(event_type="file_read")])
        assert "file_inspection" in chunk.summary

    def test_summary_contains_event_count(self) -> None:
        events = [_make_event(event_id=f"e{i}") for i in range(3)]
        chunk = ActionChunker().chunk_one(events)
        assert "3 events" in chunk.summary


class TestActionChunkerRedactionStatus:
    def test_redacted_if_any_event_redacted(self) -> None:
        events = [
            _make_event(event_id="e1", payload={"redaction_status": "clean"}),
            _make_event(event_id="e2", payload={"redaction_status": "redacted"}),
        ]
        assert ActionChunker().chunk_one(events).redaction_status == "redacted"

    def test_clean_if_all_events_clean(self) -> None:
        events = [
            _make_event(event_id="e1", payload={"redaction_status": "clean"}),
            _make_event(event_id="e2", payload={"redaction_status": "clean"}),
        ]
        assert ActionChunker().chunk_one(events).redaction_status == "clean"

    def test_unknown_if_status_missing(self) -> None:
        events = [_make_event(payload={})]
        assert ActionChunker().chunk_one(events).redaction_status == "unknown"

    def test_unknown_if_mixed_statuses(self) -> None:
        events = [
            _make_event(event_id="e1", payload={"redaction_status": "clean"}),
            _make_event(event_id="e2", payload={}),
        ]
        assert ActionChunker().chunk_one(events).redaction_status == "unknown"


class TestActionChunkerChunkOne:
    def test_chunk_one_raises_on_empty(self) -> None:
        with pytest.raises(ValueError, match="events must not be empty"):
            ActionChunker().chunk_one([])

    def test_chunk_one_ignores_turn_boundaries(self) -> None:
        events = [
            _make_event(event_id="e1", turn_id="t1"),
            _make_event(event_id="e2", turn_id="t2"),
        ]
        chunk = ActionChunker().chunk_one(events)
        assert set(chunk.event_ids) == {"e1", "e2"}

    def test_chunk_one_returns_actionchunk_instance(self) -> None:
        assert isinstance(ActionChunker().chunk_one([_make_event()]), ActionChunk)

    def test_chunk_one_session_from_first_event(self) -> None:
        events = [
            _make_event(event_id="e1", session_id="sess-A"),
            _make_event(event_id="e2", session_id="sess-B"),
        ]
        assert ActionChunker().chunk_one(events).session_id == "sess-A"
