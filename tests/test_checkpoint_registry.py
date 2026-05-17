"""Issue #126 — checkpoint registry promote / rollback / override tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from photon_action_memory.models.checkpoint import CHECKPOINT_FORMAT_V2
from photon_action_memory.models.checkpoint_builder import (
    build_action_memory_checkpoint_state_v2,
    write_action_memory_checkpoint,
)
from photon_action_memory.models.checkpoint_registry import (
    CHECKPOINT_OVERRIDE_ENV,
    CheckpointRegistry,
    CheckpointRegistryError,
)


def _build_candidate(
    registry: CheckpointRegistry,
    candidate_id: str,
    *,
    weight: float = 0.5,
) -> Path:
    registry.initialize()
    candidate_dir = registry.candidates_dir / candidate_id
    state = build_action_memory_checkpoint_state_v2(
        [{"kind": "summary", "key": f"sum-{candidate_id}", "weight": weight}],
    )
    write_action_memory_checkpoint(
        candidate_dir,
        model_version=f"action-memory-{candidate_id}",
        state=state,
        format_version=CHECKPOINT_FORMAT_V2,
        source={"feedback_max_updated_at": "2026-05-17T00:00:00.000000+00:00"},
        use_action_memory_sidecar=False,
    )
    return candidate_dir


def test_promote_sets_current_atomically(tmp_path: Path) -> None:
    registry = CheckpointRegistry(tmp_path / "registry")
    _build_candidate(registry, "ckpt-1")
    registry.register_candidate(registry.candidates_dir / "ckpt-1")

    record = registry.promote("ckpt-1", reason="initial promote")

    assert record.event == "promote"
    assert record.previous_id is None
    assert (registry.root_dir / "current").read_text(encoding="utf-8").strip() == "ckpt-1"
    assert registry.active_path() == registry.candidates_dir / "ckpt-1"
    report = json.loads(registry.report_path.read_text(encoding="utf-8"))
    assert report[-1]["candidate_id"] == "ckpt-1"


def test_promote_shifts_current_to_previous(tmp_path: Path) -> None:
    registry = CheckpointRegistry(tmp_path / "registry")
    _build_candidate(registry, "ckpt-1")
    _build_candidate(registry, "ckpt-2", weight=0.7)
    registry.promote("ckpt-1", reason="first")
    registry.promote("ckpt-2", reason="second")

    assert registry.active_path() == registry.candidates_dir / "ckpt-2"
    assert registry.previous_path() == registry.candidates_dir / "ckpt-1"


def test_rollback_restores_previous(tmp_path: Path) -> None:
    registry = CheckpointRegistry(tmp_path / "registry")
    _build_candidate(registry, "ckpt-1")
    _build_candidate(registry, "ckpt-2", weight=0.7)
    registry.promote("ckpt-1", reason="first")
    registry.promote("ckpt-2", reason="second")

    record = registry.rollback(reason="canary regression")

    assert record.event == "rollback"
    assert record.candidate_id == "ckpt-1"
    assert registry.active_path() == registry.candidates_dir / "ckpt-1"
    # And previous now points to ckpt-2 so a second rollback can undo.
    assert registry.previous_path() == registry.candidates_dir / "ckpt-2"


def test_rollback_raises_when_no_previous(tmp_path: Path) -> None:
    registry = CheckpointRegistry(tmp_path / "registry")
    _build_candidate(registry, "ckpt-1")
    registry.promote("ckpt-1", reason="first")

    with pytest.raises(CheckpointRegistryError):
        registry.rollback(reason="cannot")


def test_operator_override_disables_auto_promotion(tmp_path: Path) -> None:
    registry = CheckpointRegistry(tmp_path / "registry")
    candidate = _build_candidate(registry, "ckpt-1")
    registry.promote("ckpt-1", reason="seed")

    override_env = {CHECKPOINT_OVERRIDE_ENV: "/opt/photon/operator-checkpoint"}
    resolved = registry.resolve_active(environ=override_env)
    assert resolved == Path("/opt/photon/operator-checkpoint")
    assert registry.auto_promotion_enabled(environ=override_env) is False

    no_override_env: dict[str, str] = {}
    assert registry.resolve_active(environ=no_override_env) == candidate
    assert registry.auto_promotion_enabled(environ=no_override_env) is True


def test_register_candidate_rejects_external_path(tmp_path: Path) -> None:
    registry = CheckpointRegistry(tmp_path / "registry")
    registry.initialize()
    outside = tmp_path / "outside-ckpt"
    state = build_action_memory_checkpoint_state_v2(
        [{"kind": "summary", "key": "sum-x", "weight": 0.1}],
    )
    write_action_memory_checkpoint(
        outside,
        model_version="outside",
        state=state,
        format_version=CHECKPOINT_FORMAT_V2,
    )
    with pytest.raises(CheckpointRegistryError):
        registry.register_candidate(outside)
