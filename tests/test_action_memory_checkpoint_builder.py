"""Issue #123 / #126 — Action Memory PHOTON checkpoint builder tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from photon_action_memory.models.checkpoint import (
    CHECKPOINT_FORMAT,
    CHECKPOINT_FORMAT_V2,
    load_checkpoint_manifest,
    verify_checkpoint_integrity,
)
from photon_action_memory.models.checkpoint_builder import (
    build_action_memory_checkpoint_state,
    build_action_memory_checkpoint_state_v2,
    write_action_memory_checkpoint,
)

FIXTURE = Path(__file__).parent / "fixtures" / "photon" / "checkpoints" / "action_memory_tiny"


def test_build_state_from_feedback_records() -> None:
    state = build_action_memory_checkpoint_state(
        [
            {"kind": "summary", "key": "summary", "adopted": True},
            {"kind": "file", "target": "tests/test_session_store.py", "weight": 0.35},
            {"kind": "evidence", "evidence_id": "evt_session_failure", "weight": 0.45},
            {"kind": "failed_attempt", "action": "failed_attempt", "adopted": False},
        ],
        bias=0.1,
    )

    assert state == {
        "bias": 0.1,
        "action_weights": {"summary": 0.2, "failed_attempt": -0.1},
        "file_weights": {"tests/test_session_store.py": 0.35},
        "evidence_weights": {"evt_session_failure": 0.45},
    }


def test_write_checkpoint_creates_manifest_runtime_files_and_integrity(tmp_path: Path) -> None:
    state = build_action_memory_checkpoint_state(
        [{"kind": "next_hint", "key": "next_hint", "weight": 0.12}],
        bias=0.2,
    )

    paths = write_action_memory_checkpoint(
        tmp_path / "checkpoint",
        model_version="action-memory-test-v1",
        state=state,
    )

    manifest = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
    assert manifest["format"] == CHECKPOINT_FORMAT
    assert manifest["model_version"] == "action-memory-test-v1"
    assert manifest["state"]["action_weights"] == {"next_hint": 0.12}
    assert paths.state_path.exists()
    assert paths.weights_path.exists()
    assert paths.integrity_path is not None
    assert verify_checkpoint_integrity(paths.checkpoint_dir, strict=True) is True


def test_tiny_fixture_checkpoint_is_valid_and_small() -> None:
    manifest = load_checkpoint_manifest(FIXTURE)

    assert manifest.model_version == "action-memory-photon-tiny-v1"
    assert manifest.state["bias"] == 0.1
    assert verify_checkpoint_integrity(FIXTURE, strict=True) is True
    assert (FIXTURE / "weights.npz").stat().st_size < 1024


# ---------------------------------------------------------------------------
# Issue #126 — v2 builder + loader
# ---------------------------------------------------------------------------


def test_v2_builder_emits_summary_evidence_avoid_buckets_and_suppressed() -> None:
    state = build_action_memory_checkpoint_state_v2(
        [
            {"kind": "summary", "key": "sum-good", "weight": 0.2},
            {"kind": "summary", "key": "sum-good", "weight": 0.1},
            {"kind": "evidence", "key": "evt-a", "weight": 0.3},
            {"kind": "next_action", "key": "next-1", "weight": 0.15},
            {"kind": "avoid", "key": "avoid-1", "weight": -0.4},
            {"kind": "summary", "key": "sum-bad", "weight": 1.0, "safety_violation": True},
        ],
        bias=0.2,
    )

    assert state["bias"] == 0.2
    assert state["summary_weights"] == {"sum-good": 0.3}
    assert state["evidence_weights"] == {"evt-a": 0.3}
    assert state["next_action_weights"] == {"next-1": 0.15}
    assert state["avoid_weights"] == {"avoid-1": -0.4}
    suppressed_ids = cast(list[str], state["suppressed_ids"])
    assert "sum-bad" in suppressed_ids
    assert "sum-good" not in suppressed_ids


def test_v2_checkpoint_can_be_written_and_loaded(tmp_path: Path) -> None:
    state = build_action_memory_checkpoint_state_v2(
        [
            {"kind": "summary", "key": "sum-good", "weight": 0.2},
            {"kind": "evidence", "key": "evt-a", "weight": 0.3},
            {"kind": "summary", "key": "sum-bad", "weight": 1.0, "safety_violation": True},
        ],
    )

    paths = write_action_memory_checkpoint(
        tmp_path / "ckpt-v2",
        model_version="action-memory-v2-test",
        state=state,
        format_version=CHECKPOINT_FORMAT_V2,
        source={"feedback_max_updated_at": "2026-05-17T00:00:00.000000+00:00"},
        use_action_memory_sidecar=True,
        include_photon_runtime_stub=True,
    )

    assert paths.format == CHECKPOINT_FORMAT_V2
    assert paths.action_memory_state_path is not None
    assert paths.photon_runtime_dir is not None
    assert paths.photon_runtime_dir.is_dir()

    manifest_doc = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
    assert manifest_doc["format"] == CHECKPOINT_FORMAT_V2
    # Sidecar mode keeps the manifest state empty so big weights live in
    # action_memory_state.json.
    assert manifest_doc["state"] == {}
    assert manifest_doc["source"]["feedback_max_updated_at"]

    checkpoint = load_checkpoint_manifest(paths.checkpoint_dir, strict=True)
    assert checkpoint.format == CHECKPOINT_FORMAT_V2
    assert checkpoint.has_photon_runtime is True
    # Sidecar is merged in by the loader.
    assert checkpoint.state["summary_weights"] == {"sum-good": 0.2}
    assert checkpoint.state["evidence_weights"] == {"evt-a": 0.3}
    suppressed_ids = cast(list[str], checkpoint.state["suppressed_ids"])
    assert "sum-bad" in suppressed_ids
    assert checkpoint.source["feedback_max_updated_at"]


def test_v2_metadata_only_checkpoint_round_trips(tmp_path: Path) -> None:
    state = build_action_memory_checkpoint_state_v2(
        [
            {"kind": "summary", "key": "sum-only", "weight": 0.5},
        ],
    )

    paths = write_action_memory_checkpoint(
        tmp_path / "ckpt-v2-meta",
        model_version="action-memory-v2-meta",
        state=state,
        format_version=CHECKPOINT_FORMAT_V2,
    )
    # No sidecar, no photon_runtime — pure metadata layer.
    assert paths.action_memory_state_path is None
    assert paths.photon_runtime_dir is None

    checkpoint = load_checkpoint_manifest(paths.checkpoint_dir, strict=True)
    assert checkpoint.format == CHECKPOINT_FORMAT_V2
    assert checkpoint.has_photon_runtime is False
    assert checkpoint.state["summary_weights"] == {"sum-only": 0.5}
    assert checkpoint.state["suppressed_ids"] == []
