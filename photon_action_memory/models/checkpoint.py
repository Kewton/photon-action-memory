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
CHECKPOINT_FORMAT_V2 = "photon-action-memory.v2"
SUPPORTED_CHECKPOINT_FORMATS: frozenset[str] = frozenset({CHECKPOINT_FORMAT, CHECKPOINT_FORMAT_V2})
CHECKPOINT_MANIFEST = "manifest.json"
INTEGRITY_FORMAT_VERSION = "1"
STATE_FILENAME = "state.json"
WEIGHTS_FILENAME = "weights.npz"
INTEGRITY_FILENAME = "integrity.json"
ACTION_MEMORY_STATE_FILENAME = "action_memory_state.json"
PROMOTION_REPORT_FILENAME = "promotion_report.json"
PHOTON_RUNTIME_DIRNAME = "photon_runtime"

ALLOWED_STATE_KEYS = frozenset(
    {
        "action_weights",
        "bias",
        "evidence_weights",
        "file_weights",
    }
)
# v2 adds richer per-bucket weights and a suppressed_ids set without dropping
# any of the v1 keys, so a v2 manifest can still be loaded by the v1 scoring
# path with the legacy buckets continuing to behave as before.
ALLOWED_STATE_KEYS_V2 = ALLOWED_STATE_KEYS | frozenset(
    {
        "summary_weights",
        "next_action_weights",
        "avoid_weights",
        "suppressed_ids",
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
    format: str = CHECKPOINT_FORMAT
    source: dict[str, object] = field(default_factory=dict)
    has_photon_runtime: bool = False


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
    """Load and validate a small PHOTON runtime checkpoint manifest.

    Accepts both the v1 (``photon-action-memory.mlx.v1``) and v2
    (``photon-action-memory.v2``) manifest formats. v2 manifests may
    additionally carry a ``source`` block and an ``action_memory_state``
    sidecar file; the metadata layer is layered onto ``state`` so legacy
    callers continue to work without branching.
    """
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
    fmt = raw.get("format")
    if fmt not in SUPPORTED_CHECKPOINT_FORMATS:
        raise CheckpointInvalid(
            f"checkpoint manifest format must be one of {sorted(SUPPORTED_CHECKPOINT_FORMATS)!r}"
        )

    model_version = raw.get("model_version")
    if not isinstance(model_version, str) or not model_version.strip():
        raise CheckpointInvalid("checkpoint manifest requires a non-empty model_version")

    state = raw.get("state", {})
    if not isinstance(state, dict):
        raise CheckpointInvalid("checkpoint state must be an object")

    allowed = ALLOWED_STATE_KEYS_V2 if fmt == CHECKPOINT_FORMAT_V2 else ALLOWED_STATE_KEYS
    clean_state, warnings = _clean_state(state, strict=strict, allowed=allowed)

    source_raw = raw.get("source")
    source: dict[str, object] = dict(source_raw) if isinstance(source_raw, dict) else {}
    checkpoint_dir = manifest_path.parent
    sidecar_state_path = checkpoint_dir / ACTION_MEMORY_STATE_FILENAME
    if sidecar_state_path.exists():
        clean_state = _merge_action_memory_sidecar(
            clean_state,
            sidecar_state_path,
            warnings=warnings,
            strict=strict,
            allowed=allowed,
        )
    has_runtime = (checkpoint_dir / PHOTON_RUNTIME_DIRNAME).is_dir()

    return PhotonCheckpoint(
        path=manifest_path,
        model_version=model_version.strip(),
        state=clean_state,
        warnings=tuple(warnings),
        format=fmt,
        source=source,
        has_photon_runtime=has_runtime,
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


def _clean_state(
    raw_state: dict[str, Any],
    *,
    strict: bool,
    allowed: frozenset[str] = ALLOWED_STATE_KEYS,
) -> tuple[dict[str, object], list[str]]:
    unknown_keys = sorted(set(raw_state) - allowed)
    if unknown_keys and strict:
        joined = ", ".join(unknown_keys)
        raise CheckpointInvalid(f"checkpoint state contains unknown keys: {joined}")

    warnings = [f"dropped unknown checkpoint state key: {key}" for key in unknown_keys]
    return (
        {key: value for key, value in raw_state.items() if key in allowed},
        warnings,
    )


def _merge_action_memory_sidecar(
    state: dict[str, object],
    sidecar_path: Path,
    *,
    warnings: list[str],
    strict: bool,
    allowed: frozenset[str],
) -> dict[str, object]:
    """Merge ``action_memory_state.json`` keys into the manifest state.

    The sidecar lets a v2 checkpoint keep large weight dictionaries out of
    the manifest itself. Manifest values win on collision so a hand-edited
    operator override stays authoritative.
    """
    try:
        raw = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if strict:
            raise CheckpointInvalid(
                f"action_memory_state sidecar is not valid JSON: {sidecar_path}"
            ) from exc
        warnings.append(f"could not read action_memory_state sidecar: {sidecar_path.name}")
        return state
    if not isinstance(raw, dict):
        if strict:
            raise CheckpointInvalid("action_memory_state sidecar must decode to an object")
        warnings.append("action_memory_state sidecar must decode to an object")
        return state
    cleaned, extra_warnings = _clean_state(raw, strict=strict, allowed=allowed)
    warnings.extend(extra_warnings)
    merged: dict[str, object] = dict(cleaned)
    merged.update(state)
    return merged


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
