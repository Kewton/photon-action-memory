"""Issue #123 — Action Memory PHOTON checkpoint builder and fixture tests."""

from __future__ import annotations

import json
from pathlib import Path

from photon_action_memory.models.checkpoint import (
    CHECKPOINT_FORMAT,
    load_checkpoint_manifest,
    verify_checkpoint_integrity,
)
from photon_action_memory.models.checkpoint_builder import (
    build_action_memory_checkpoint_state,
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
