"""Issue #126 — action-memory-feedback.v1 exporter tests."""

from __future__ import annotations

import json
import sqlite3
from io import StringIO
from pathlib import Path

from photon_action_memory.eval.feedback_export import (
    FEEDBACK_EXPORT_SCHEMA,
    export_action_memory_feedback,
    iter_export_jsonl,
    write_export_jsonl,
)
from photon_action_memory.eval.ranking_log import (
    LABEL_ADOPTED_FAILURE,
    LABEL_ADOPTED_SAFETY,
    LABEL_ADOPTED_SUCCESS,
    LABEL_OMITTED_BY_GATE,
    LABEL_PARTIAL,
    RankingLogEntry,
    RankingLogOutcome,
    RankingLogStore,
)


def _store(tmp_path: Path) -> RankingLogStore:
    connection = sqlite3.connect(tmp_path / "store.sqlite")
    connection.row_factory = sqlite3.Row
    return RankingLogStore(connection)


def _record(
    store: RankingLogStore,
    summary_id: str,
    *,
    request_id: str = "pack-1",
    position: int = 0,
    selected: bool = True,
    omitted_reason: str | None = None,
    score: float = 0.5,
) -> None:
    store.record_entries(
        [
            RankingLogEntry(
                context_pack_request_id=request_id,
                summary_id=summary_id,
                position=position,
                selected=selected,
                omitted_reason=omitted_reason,
                score=score,
            )
        ]
    )


def _set_outcome(
    store: RankingLogStore,
    summary_id: str,
    family: str,
    *,
    request_id: str = "pack-1",
    adoption_status: str = "adopted",
) -> None:
    store.update_outcomes(
        [
            RankingLogOutcome(
                context_pack_request_id=request_id,
                summary_id=summary_id,
                outcome_family=family,  # type: ignore[arg-type]
                adoption_status=adoption_status,
            )
        ]
    )


def test_export_carries_outcome_family_and_signed_weights(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record(store, "sum-good", position=0)
    _record(store, "sum-bad", position=1)
    _record(store, "sum-partial", position=2)
    _record(store, "sum-omitted", position=3, selected=False, omitted_reason="quality_gate")
    _record(store, "sum-not-selected", position=4, selected=False, omitted_reason="budget")

    _set_outcome(store, "sum-good", "success")
    _set_outcome(store, "sum-bad", "failure")
    _set_outcome(store, "sum-partial", "success", adoption_status="partial")

    result = export_action_memory_feedback(store)
    by_key = {(record.bucket, record.key): record for record in result.records}

    assert by_key[("summary_weights", "sum-good")].source_label == LABEL_ADOPTED_SUCCESS
    assert by_key[("summary_weights", "sum-good")].weight > 0

    assert by_key[("summary_weights", "sum-bad")].source_label == LABEL_ADOPTED_FAILURE
    assert by_key[("summary_weights", "sum-bad")].weight < 0

    partial = by_key[("summary_weights", "sum-partial")]
    assert partial.source_label == LABEL_PARTIAL
    # Partial with success outcome → positive weight.
    assert partial.weight > 0

    omitted = by_key[("summary_weights", "sum-omitted")]
    assert omitted.source_label == LABEL_OMITTED_BY_GATE
    # Gate omissions are reported but never as positive weights.
    assert omitted.weight == 0.0

    not_selected = by_key[("summary_weights", "sum-not-selected")]
    assert not_selected.source_label == "not_selected"
    assert not_selected.weight < 0


def test_export_marks_safety_violations_for_suppression(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record(store, "sum-unsafe")
    _set_outcome(store, "sum-unsafe", "safety")

    result = export_action_memory_feedback(store)

    assert result.records, "expected at least one record"
    assert result.safety_violation_count == 1
    record = result.records[0]
    assert record.safety_violation is True
    assert record.source_label == LABEL_ADOPTED_SAFETY
    # Safety records still get a strongly negative weight so the builder
    # routes them to suppressed_ids rather than amplifying them.
    assert record.weight <= -0.5


def test_export_manifest_carries_feedback_max_updated_at(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record(store, "sum-good")
    _set_outcome(store, "sum-good", "success")

    result = export_action_memory_feedback(store)
    manifest = result.manifest_source()

    assert manifest["schema"] == FEEDBACK_EXPORT_SCHEMA
    assert manifest["feedback_max_updated_at"]
    assert manifest["feedback_record_count"] == 1


def test_export_jsonl_round_trip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record(store, "sum-good")
    _set_outcome(store, "sum-good", "success")
    result = export_action_memory_feedback(store)

    path = tmp_path / "out.jsonl"
    write_export_jsonl(result, path)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 2
    header = json.loads(lines[0])
    assert header["schema"] == FEEDBACK_EXPORT_SCHEMA
    assert header["source"]["feedback_max_updated_at"]
    record = json.loads(lines[1])
    assert record["bucket"] == "summary_weights"
    assert record["source_label"] == LABEL_ADOPTED_SUCCESS

    # Same content can be streamed without writing a file.
    buffer = StringIO()
    for line in iter_export_jsonl(result):
        buffer.write(line + "\n")
    assert buffer.getvalue() == path.read_text(encoding="utf-8")


def test_export_does_not_emit_raw_text_fields(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record(store, "sum-good")
    _set_outcome(store, "sum-good", "success")
    result = export_action_memory_feedback(store)

    for line in iter_export_jsonl(result):
        payload = json.loads(line)
        # The exporter has a fixed schema — confirm nobody added a raw_text
        # field by accident.
        forbidden = {"raw_text", "text", "evidence_text", "prompt", "stdout"}
        assert not (forbidden & set(payload.keys()))
