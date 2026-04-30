"""Runtime checkpoint I/O for optional PHOTON adapters.

This module intentionally uses only the Python standard library. Runtime paths
can import it without importing training modules or optional MLX dependencies.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

CHECKPOINT_FORMAT = "photon-action-memory.mlx.v1"
CHECKPOINT_MANIFEST = "manifest.json"
INTEGRITY_FORMAT_VERSION = "1"
STATE_FILENAME = "state.json"
WEIGHTS_FILENAME = "weights.npz"
INTEGRITY_FILENAME = "integrity.json"
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


@dataclass
class CheckpointState:
    """Runtime DTO for checkpoint ``state.json``.

    The fields mirror the training state shape used by the reference PHOTON
    checkpoint writer, while remaining independent from training-only modules.
    """

    step: int = 0
    best_val_loss: float = float("inf")
    best_step: int = 0
    patience_counter: int = 0
    train_losses: list[float] = field(default_factory=list)
    val_losses: list[float] = field(default_factory=list)


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


def load_checkpoint(path: str | Path, *, verify_integrity: bool = False) -> CheckpointState:
    """Load checkpoint state from ``path``.

    ``verify_integrity=True`` requires an integrity manifest. When false, a
    missing manifest only emits a warning so legacy checkpoints can still be
    probed. Hash mismatches always raise.
    """

    checkpoint_dir = Path(path)
    verify_checkpoint_integrity(checkpoint_dir, strict=verify_integrity)
    return load_checkpoint_state(checkpoint_dir)


def load_checkpoint_state(path: str | Path) -> CheckpointState:
    """Load and validate ``state.json`` without importing model code."""

    state_path = Path(path) / STATE_FILENAME
    try:
        raw_state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{state_path} is not valid JSON") from exc

    if not isinstance(raw_state, dict):
        raise ValueError(f"{state_path} must decode to an object, got {type(raw_state).__name__}")

    known_fields = {item.name for item in fields(CheckpointState)}
    unknown_fields = sorted(set(raw_state) - known_fields)
    if unknown_fields:
        _logger.warning("Ignoring unknown checkpoint state keys: %s", unknown_fields)

    filtered = {key: raw_state[key] for key in known_fields if key in raw_state}
    return _checkpoint_state_from_mapping(filtered, state_path)


def verify_checkpoint_integrity(path: str | Path, *, strict: bool = False) -> bool:
    """Verify ``integrity.json`` hashes for ``state.json`` and ``weights.npz``.

    Returns true when a manifest was present and matched. Returns false when the
    manifest is absent in non-strict mode. Raises for strict missing manifests,
    malformed manifests, missing hashed files, or hash mismatches.
    """

    checkpoint_dir = Path(path)
    integrity_path = checkpoint_dir / INTEGRITY_FILENAME
    if not integrity_path.exists():
        if strict:
            raise FileNotFoundError(
                f"{INTEGRITY_FILENAME} missing at {integrity_path} with strict verification"
            )
        _logger.warning(
            "%s missing at %s; checkpoint integrity cannot be verified",
            INTEGRITY_FILENAME,
            integrity_path,
        )
        return False

    try:
        manifest = json.loads(integrity_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{integrity_path} is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError(
            f"{integrity_path} must decode to an object, got {type(manifest).__name__}"
        )

    expected_raw = {
        WEIGHTS_FILENAME: manifest.get("weights_sha256"),
        STATE_FILENAME: manifest.get("state_sha256"),
    }
    missing_hashes = [name for name, digest in expected_raw.items() if not isinstance(digest, str)]
    if missing_hashes:
        raise ValueError(
            f"{integrity_path} missing SHA-256 entries for: {', '.join(missing_hashes)}"
        )
    expected = {name: str(digest) for name, digest in expected_raw.items()}

    for filename, expected_digest in expected.items():
        actual_digest = _sha256_file(checkpoint_dir / filename)
        if actual_digest != expected_digest:
            raise ValueError(
                "checkpoint integrity check failed for "
                f"{filename}: expected {expected_digest[:12]}, got {actual_digest[:12]}"
            )
    return True


def write_integrity_manifest(path: str | Path) -> None:
    """Write an integrity manifest for an existing runtime checkpoint."""

    checkpoint_dir = Path(path)
    manifest = {
        "format_version": INTEGRITY_FORMAT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "weights_sha256": _sha256_file(checkpoint_dir / WEIGHTS_FILENAME),
        "state_sha256": _sha256_file(checkpoint_dir / STATE_FILENAME),
    }
    integrity_path = checkpoint_dir / INTEGRITY_FILENAME
    tmp_path = checkpoint_dir / f"{INTEGRITY_FILENAME}.tmp"
    tmp_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp_path, integrity_path)


def _manifest_path(path: Path) -> Path:
    if path.is_dir():
        return path / CHECKPOINT_MANIFEST
    return path


def _clean_state(raw_state: dict[str, Any], *, strict: bool) -> tuple[dict[str, object], list[str]]:
    unknown_keys = sorted(set(raw_state) - ALLOWED_STATE_KEYS)
    if unknown_keys and strict:
        joined = ", ".join(unknown_keys)
        raise CheckpointInvalid(f"checkpoint state contains unknown keys: {joined}")

    warnings = [f"dropped unknown checkpoint state key: {key}" for key in unknown_keys]
    return (
        {key: value for key, value in raw_state.items() if key in ALLOWED_STATE_KEYS},
        warnings,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checkpoint_state_from_mapping(values: dict[str, Any], source: Path) -> CheckpointState:
    coerced = _coerce_state_fields(values, source)
    return CheckpointState(
        step=coerced.get("step", 0),
        best_val_loss=coerced.get("best_val_loss", float("inf")),
        best_step=coerced.get("best_step", 0),
        patience_counter=coerced.get("patience_counter", 0),
        train_losses=coerced.get("train_losses", []),
        val_losses=coerced.get("val_losses", []),
    )


def _coerce_state_fields(values: dict[str, Any], source: Path) -> dict[str, Any]:
    coerced: dict[str, object] = {}
    for key, value in values.items():
        if key in {"step", "best_step", "patience_counter"}:
            if not isinstance(value, int):
                raise ValueError(f"{source} field {key!r} must be an integer")
            coerced[key] = value
            continue
        if key == "best_val_loss":
            if not isinstance(value, int | float):
                raise ValueError(f"{source} field {key!r} must be numeric")
            coerced[key] = float(value)
            continue
        if key in {"train_losses", "val_losses"}:
            coerced[key] = _coerce_loss_list(value, source, key)
            continue
    return coerced


def _coerce_loss_list(value: object, source: Path, key: str) -> list[float]:
    if not isinstance(value, list):
        raise ValueError(f"{source} field {key!r} must be a list")
    losses: list[float] = []
    for item in value:
        if not isinstance(item, int | float):
            raise ValueError(f"{source} field {key!r} must contain only numbers")
        losses.append(float(item))
    return losses
