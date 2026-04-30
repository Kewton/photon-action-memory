from __future__ import annotations

import importlib
import json
import logging
import sys
from pathlib import Path

import pytest

from photon_action_memory.models.checkpoint import (
    CheckpointState,
    load_checkpoint,
    load_checkpoint_state,
    verify_checkpoint_integrity,
    write_integrity_manifest,
)
from photon_action_memory.models.photon_adapter import (
    CHECKPOINT_ENV,
    load_configured_checkpoint_state,
)


def _write_checkpoint(
    path: Path,
    *,
    state: dict[str, object] | None = None,
    integrity: bool = True,
) -> None:
    path.mkdir()
    (path / "weights.npz").write_bytes(b"runtime checkpoint weights")
    (path / "state.json").write_text(
        json.dumps(state if state is not None else {"step": 42, "best_val_loss": 1.25}),
        encoding="utf-8",
    )
    if integrity:
        write_integrity_manifest(path)


def test_checkpoint_module_import_does_not_pull_training_or_mlx_modules() -> None:
    for module_name in list(sys.modules):
        if (
            module_name == "mlx"
            or module_name.startswith("mlx.")
            or module_name == "photon_action_memory.training"
            or module_name.startswith("photon_action_memory.training.")
        ):
            sys.modules.pop(module_name, None)
    sys.modules.pop("photon_action_memory.models.checkpoint", None)

    importlib.import_module("photon_action_memory.models.checkpoint")

    assert "mlx" not in sys.modules
    assert "photon_action_memory.training" not in sys.modules


def test_load_checkpoint_reads_state_and_verifies_integrity(tmp_path: Path) -> None:
    checkpoint_dir = tmp_path / "ckpt"
    _write_checkpoint(
        checkpoint_dir,
        state={
            "step": 200,
            "best_val_loss": 0.75,
            "best_step": 180,
            "patience_counter": 2,
            "train_losses": [1, 0.9],
            "val_losses": [1.2, 0.8],
        },
    )

    assert verify_checkpoint_integrity(checkpoint_dir, strict=True) is True
    loaded = load_checkpoint(checkpoint_dir, verify_integrity=True)

    assert loaded == CheckpointState(
        step=200,
        best_val_loss=0.75,
        best_step=180,
        patience_counter=2,
        train_losses=[1.0, 0.9],
        val_losses=[1.2, 0.8],
    )


def test_missing_integrity_warns_by_default_but_strict_mode_raises(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    checkpoint_dir = tmp_path / "ckpt"
    _write_checkpoint(checkpoint_dir, integrity=False)

    with caplog.at_level(logging.WARNING, logger="photon_action_memory.models.checkpoint"):
        loaded = load_checkpoint(checkpoint_dir)

    assert loaded.step == 42
    assert any("integrity" in record.message for record in caplog.records)

    with pytest.raises(FileNotFoundError):
        load_checkpoint(checkpoint_dir, verify_integrity=True)


def test_integrity_hash_mismatch_raises(tmp_path: Path) -> None:
    checkpoint_dir = tmp_path / "ckpt"
    _write_checkpoint(checkpoint_dir)
    (checkpoint_dir / "state.json").write_text(json.dumps({"step": 999}), encoding="utf-8")

    with pytest.raises(ValueError, match="integrity"):
        load_checkpoint(checkpoint_dir)


def test_unknown_state_keys_warn_and_drop(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    checkpoint_dir = tmp_path / "ckpt"
    _write_checkpoint(
        checkpoint_dir,
        state={"step": 5, "future_state": "ignored"},
        integrity=False,
    )

    with caplog.at_level(logging.WARNING, logger="photon_action_memory.models.checkpoint"):
        loaded = load_checkpoint_state(checkpoint_dir)

    assert loaded == CheckpointState(step=5)
    assert any("future_state" in record.message for record in caplog.records)
    assert not hasattr(loaded, "future_state")


def test_invalid_state_json_raises(tmp_path: Path) -> None:
    checkpoint_dir = tmp_path / "ckpt"
    _write_checkpoint(checkpoint_dir, state=[1, 2, 3], integrity=False)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="must decode to an object"):
        load_checkpoint_state(checkpoint_dir)


def test_adapter_returns_unavailable_for_missing_or_invalid_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CHECKPOINT_ENV, str(tmp_path / "missing"))
    assert load_configured_checkpoint_state() is None

    checkpoint_dir = tmp_path / "invalid"
    _write_checkpoint(checkpoint_dir, integrity=False)
    (checkpoint_dir / "state.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv(CHECKPOINT_ENV, str(checkpoint_dir))

    assert load_configured_checkpoint_state() is None
