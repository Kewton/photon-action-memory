"""Build small Action Memory PHOTON runtime checkpoints.

The builder intentionally writes the same runtime files consumed by
``PhotonMLXAdapter`` while staying independent from MLX and training-only code.
It is meant for local scoring checkpoints and tiny CI fixtures, not for storing
large model artifacts in this repository.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from photon_action_memory.models.checkpoint import (
    ALLOWED_STATE_KEYS,
    CHECKPOINT_FORMAT,
    CHECKPOINT_MANIFEST,
    INTEGRITY_FILENAME,
    STATE_FILENAME,
    WEIGHTS_FILENAME,
    write_integrity_manifest,
)

WeightBucket = Literal["action_weights", "file_weights", "evidence_weights"]

_KIND_BUCKETS: Mapping[str, WeightBucket] = {
    "action": "action_weights",
    "summary": "action_weights",
    "next_hint": "action_weights",
    "failed_attempt": "action_weights",
    "file": "file_weights",
    "evidence": "evidence_weights",
}
_DEFAULT_WEIGHTS_PAYLOAD = b"tiny action-memory PHOTON checkpoint placeholder\n"


@dataclass(frozen=True)
class ActionMemoryCheckpointPaths:
    """Files written for a runtime Action Memory checkpoint."""

    checkpoint_dir: Path
    manifest_path: Path
    state_path: Path
    weights_path: Path
    integrity_path: Path | None
    model_version: str


def build_action_memory_checkpoint_state(
    records: Iterable[Mapping[str, object]],
    *,
    bias: float = 0.5,
) -> dict[str, object]:
    """Build a runtime scoring state from normalized feedback/eval records.

    Each record can specify:

    - ``kind`` or ``bucket``: ``summary``, ``next_hint``, ``failed_attempt``,
      ``file``, or ``evidence``.
    - ``key`` / ``target`` / ``evidence_id`` / ``action``: the value to weight.
    - ``weight``: explicit numeric weight.
    - ``adopted``: when ``weight`` is absent, true maps to ``+0.2`` and false
      maps to ``-0.1``.
    """

    action_weights: dict[str, float] = {}
    file_weights: dict[str, float] = {}
    evidence_weights: dict[str, float] = {}
    buckets: dict[WeightBucket, dict[str, float]] = {
        "action_weights": action_weights,
        "file_weights": file_weights,
        "evidence_weights": evidence_weights,
    }

    for index, record in enumerate(records):
        bucket = _bucket_from_record(record, index)
        key = _key_from_record(record, index)
        weight = _weight_from_record(record, index)
        current = buckets[bucket].get(key, 0.0)
        buckets[bucket][key] = round(current + weight, 4)

    return {
        "bias": _coerce_number(bias, "bias"),
        "action_weights": action_weights,
        "file_weights": file_weights,
        "evidence_weights": evidence_weights,
    }


def write_action_memory_checkpoint(
    path: str | Path,
    *,
    model_version: str,
    state: Mapping[str, object],
    training_state: Mapping[str, object] | None = None,
    weights_payload: bytes = _DEFAULT_WEIGHTS_PAYLOAD,
    write_integrity: bool = True,
) -> ActionMemoryCheckpointPaths:
    """Write a small runtime checkpoint directory.

    The manifest carries scorer weights. ``state.json`` and ``weights.npz`` are
    present so strict integrity mode can verify the checkpoint package without
    needing to import MLX or download any model.
    """

    version = model_version.strip()
    if not version:
        raise ValueError("model_version must be non-empty")
    checkpoint_dir = Path(path)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "format": CHECKPOINT_FORMAT,
        "model_version": version,
        "state": _clean_runtime_state(state),
    }
    manifest_path = checkpoint_dir / CHECKPOINT_MANIFEST
    state_path = checkpoint_dir / STATE_FILENAME
    weights_path = checkpoint_dir / WEIGHTS_FILENAME

    _atomic_write_json(manifest_path, manifest)
    _atomic_write_json(state_path, _default_training_state() | dict(training_state or {}))
    _atomic_write_bytes(weights_path, weights_payload)

    integrity_path: Path | None = None
    if write_integrity:
        write_integrity_manifest(checkpoint_dir)
        integrity_path = checkpoint_dir / INTEGRITY_FILENAME

    return ActionMemoryCheckpointPaths(
        checkpoint_dir=checkpoint_dir,
        manifest_path=manifest_path,
        state_path=state_path,
        weights_path=weights_path,
        integrity_path=integrity_path,
        model_version=version,
    )


def _bucket_from_record(record: Mapping[str, object], index: int) -> WeightBucket:
    raw_bucket = record.get("bucket")
    if isinstance(raw_bucket, str) and raw_bucket in _KIND_BUCKETS.values():
        return raw_bucket  # type: ignore[return-value]

    raw_kind = record.get("kind")
    if isinstance(raw_kind, str):
        bucket = _KIND_BUCKETS.get(raw_kind.strip().lower())
        if bucket is not None:
            return bucket
    raise ValueError(f"record {index} must include a supported kind or bucket")


def _key_from_record(record: Mapping[str, object], index: int) -> str:
    for field in ("key", "target", "evidence_id", "summary_id", "action"):
        raw = record.get(field)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    raise ValueError(f"record {index} must include a non-empty key/target/evidence_id/action")


def _weight_from_record(record: Mapping[str, object], index: int) -> float:
    raw_weight = record.get("weight")
    if raw_weight is not None:
        return _coerce_number(raw_weight, f"record {index} weight")

    raw_adopted = record.get("adopted")
    if isinstance(raw_adopted, bool):
        return 0.2 if raw_adopted else -0.1
    return 0.0


def _clean_runtime_state(state: Mapping[str, object]) -> dict[str, object]:
    unknown = sorted(set(state) - ALLOWED_STATE_KEYS)
    if unknown:
        raise ValueError(f"runtime state contains unsupported keys: {', '.join(unknown)}")

    clean: dict[str, object] = {}
    clean["bias"] = _coerce_number(state.get("bias", 0.5), "bias")
    for bucket in ("action_weights", "file_weights", "evidence_weights"):
        clean[bucket] = _clean_weight_mapping(state.get(bucket, {}), bucket)
    return clean


def _clean_weight_mapping(raw: object, label: str) -> dict[str, float]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{label} must be an object")
    clean: dict[str, float] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"{label} keys must be non-empty strings")
        clean[key.strip()] = _coerce_number(value, f"{label}.{key}")
    return clean


def _coerce_number(raw: object, label: str) -> float:
    if not isinstance(raw, int | float) or isinstance(raw, bool):
        raise ValueError(f"{label} must be numeric")
    return round(float(raw), 4)


def _default_training_state() -> dict[str, object]:
    return {
        "step": 0,
        "best_val_loss": 0.0,
        "best_step": 0,
        "patience_counter": 0,
        "train_losses": [],
        "val_losses": [],
    }


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_bytes(payload)
    os.replace(tmp_path, path)


__all__ = [
    "ActionMemoryCheckpointPaths",
    "build_action_memory_checkpoint_state",
    "write_action_memory_checkpoint",
]
