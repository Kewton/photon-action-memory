"""Runtime checkpoint manifest I/O for optional PHOTON adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CHECKPOINT_FORMAT = "photon-action-memory.mlx.v1"
CHECKPOINT_MANIFEST = "manifest.json"
ALLOWED_STATE_KEYS = frozenset(
    {
        "action_weights",
        "bias",
        "evidence_weights",
        "file_weights",
    }
)


class CheckpointError(RuntimeError):
    """Base class for checkpoint loading failures."""


class CheckpointUnavailable(CheckpointError):
    """Raised when a checkpoint path is absent or missing."""


class CheckpointInvalid(CheckpointError):
    """Raised when a checkpoint manifest cannot be used."""


@dataclass(frozen=True)
class PhotonCheckpoint:
    """Validated checkpoint manifest for runtime scoring."""

    path: Path
    model_version: str
    state: dict[str, object]
    warnings: tuple[str, ...] = ()


def load_checkpoint_manifest(path: str | Path, *, strict: bool = False) -> PhotonCheckpoint:
    """Load and validate a small PHOTON runtime checkpoint manifest."""
    manifest_path = _manifest_path(Path(path))
    if not manifest_path.exists():
        raise CheckpointUnavailable(f"checkpoint manifest not found: {manifest_path}")

    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CheckpointUnavailable(f"checkpoint manifest cannot be read: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise CheckpointInvalid(f"checkpoint manifest is not valid JSON: {manifest_path}") from exc

    if not isinstance(raw, dict):
        raise CheckpointInvalid("checkpoint manifest must be a JSON object")
    if raw.get("format") != CHECKPOINT_FORMAT:
        raise CheckpointInvalid(f"checkpoint manifest format must be {CHECKPOINT_FORMAT!r}")

    model_version = raw.get("model_version")
    if not isinstance(model_version, str) or not model_version.strip():
        raise CheckpointInvalid("checkpoint manifest requires a non-empty model_version")

    state = raw.get("state", {})
    if not isinstance(state, dict):
        raise CheckpointInvalid("checkpoint state must be an object")

    clean_state, warnings = _clean_state(state, strict=strict)
    return PhotonCheckpoint(
        path=manifest_path,
        model_version=model_version.strip(),
        state=clean_state,
        warnings=tuple(warnings),
    )


def _manifest_path(path: Path) -> Path:
    if path.is_dir():
        return path / CHECKPOINT_MANIFEST
    return path


def _clean_state(raw_state: dict[str, Any], *, strict: bool) -> tuple[dict[str, object], list[str]]:
    unknown_keys = sorted(set(raw_state) - ALLOWED_STATE_KEYS)
    if unknown_keys and strict:
        joined = ", ".join(unknown_keys)
        raise CheckpointInvalid(f"checkpoint state contains unknown keys: {joined}")

    warnings = [
        f"dropped unknown checkpoint state key: {key}"
        for key in unknown_keys
    ]
    return (
        {key: value for key, value in raw_state.items() if key in ALLOWED_STATE_KEYS},
        warnings,
    )
