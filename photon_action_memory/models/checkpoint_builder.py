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
    ACTION_MEMORY_STATE_FILENAME,
    ALLOWED_STATE_KEYS,
    ALLOWED_STATE_KEYS_V2,
    CHECKPOINT_FORMAT,
    CHECKPOINT_FORMAT_V2,
    CHECKPOINT_MANIFEST,
    INTEGRITY_FILENAME,
    PHOTON_RUNTIME_DIRNAME,
    STATE_FILENAME,
    WEIGHTS_FILENAME,
    write_integrity_manifest,
)

WeightBucket = Literal["action_weights", "file_weights", "evidence_weights"]
WeightBucketV2 = Literal[
    "summary_weights",
    "evidence_weights",
    "next_action_weights",
    "file_weights",
    "avoid_weights",
]

_KIND_BUCKETS: Mapping[str, WeightBucket] = {
    "action": "action_weights",
    "summary": "action_weights",
    "next_hint": "action_weights",
    "failed_attempt": "action_weights",
    "file": "file_weights",
    "evidence": "evidence_weights",
}
_KIND_BUCKETS_V2: Mapping[str, WeightBucketV2] = {
    "summary": "summary_weights",
    "action_summary": "summary_weights",
    "evidence": "evidence_weights",
    "next_action": "next_action_weights",
    "next_hint": "next_action_weights",
    "file": "file_weights",
    "avoid": "avoid_weights",
    "failed_attempt": "avoid_weights",
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
    format: str = CHECKPOINT_FORMAT
    action_memory_state_path: Path | None = None
    photon_runtime_dir: Path | None = None


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
    format_version: str = CHECKPOINT_FORMAT,
    source: Mapping[str, object] | None = None,
    use_action_memory_sidecar: bool = False,
    include_photon_runtime_stub: bool = False,
) -> ActionMemoryCheckpointPaths:
    """Write a small runtime checkpoint directory.

    The manifest carries scorer weights. ``state.json`` and ``weights.npz`` are
    present so strict integrity mode can verify the checkpoint package without
    needing to import MLX or download any model.

    ``format_version`` selects between the v1 (``photon-action-memory.mlx.v1``)
    and v2 (``photon-action-memory.v2``) manifest formats. v2 enables the
    richer Phase 2 buckets (summary / next_action / avoid / suppressed_ids)
    and may carry a ``source`` block plus an optional
    ``action_memory_state.json`` sidecar.
    """

    version = model_version.strip()
    if not version:
        raise ValueError("model_version must be non-empty")
    if format_version not in (CHECKPOINT_FORMAT, CHECKPOINT_FORMAT_V2):
        raise ValueError(f"unsupported format_version: {format_version!r}")
    if use_action_memory_sidecar and format_version != CHECKPOINT_FORMAT_V2:
        raise ValueError("action_memory_state sidecar requires format v2")
    if include_photon_runtime_stub and format_version != CHECKPOINT_FORMAT_V2:
        raise ValueError("photon_runtime requires format v2")

    checkpoint_dir = Path(path)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    cleaned_state = _clean_runtime_state(state, format_version=format_version)
    manifest: dict[str, object] = {
        "format": format_version,
        "model_version": version,
    }
    sidecar_path: Path | None = None
    if use_action_memory_sidecar:
        manifest["state"] = {}
        sidecar_path = checkpoint_dir / ACTION_MEMORY_STATE_FILENAME
        _atomic_write_json(sidecar_path, cleaned_state)
    else:
        manifest["state"] = cleaned_state
    if source is not None:
        manifest["source"] = dict(source)

    manifest_path = checkpoint_dir / CHECKPOINT_MANIFEST
    state_path = checkpoint_dir / STATE_FILENAME
    weights_path = checkpoint_dir / WEIGHTS_FILENAME

    _atomic_write_json(manifest_path, manifest)
    _atomic_write_json(state_path, _default_training_state() | dict(training_state or {}))
    _atomic_write_bytes(weights_path, weights_payload)

    runtime_dir: Path | None = None
    if include_photon_runtime_stub:
        runtime_dir = checkpoint_dir / PHOTON_RUNTIME_DIRNAME
        runtime_dir.mkdir(parents=True, exist_ok=True)
        marker = runtime_dir / "README.md"
        if not marker.exists():
            marker.write_text(
                "# photon_runtime placeholder\n\n"
                "This directory marks the checkpoint as carrying an optional "
                "photon_runtime layer. The current build does not ship slim-ported "
                "MLX code; see photon_action_memory/photon_runtime/UPSTREAM.md.\n",
                encoding="utf-8",
            )

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
        format=format_version,
        action_memory_state_path=sidecar_path,
        photon_runtime_dir=runtime_dir,
    )


def build_action_memory_checkpoint_state_v2(
    records: Iterable[Mapping[str, object]],
    *,
    bias: float = 0.5,
) -> dict[str, object]:
    """Aggregate ``action-memory-feedback.v1`` records into a v2 state.

    Records emitted by :mod:`photon_action_memory.eval.feedback_export` carry
    ``kind``, ``key``, ``weight``, and ``safety_violation``. Safety
    violations bypass the weight aggregation and land in
    ``suppressed_ids`` so the scorer can ban them outright.
    """
    buckets: dict[str, object] = {
        "summary_weights": {},
        "evidence_weights": {},
        "next_action_weights": {},
        "file_weights": {},
        "avoid_weights": {},
    }
    suppressed: set[str] = set()

    for index, record in enumerate(records):
        key = _key_from_record(record, index)
        if record.get("safety_violation") is True:
            suppressed.add(key)
            continue
        bucket = _bucket_from_record_v2(record, index)
        weight = _weight_from_record(record, index)
        bucket_values = buckets[bucket]
        assert isinstance(bucket_values, dict)
        current = float(bucket_values.get(key, 0.0))
        bucket_values[key] = round(current + weight, 4)

    state: dict[str, object] = {"bias": _coerce_number(bias, "bias")}
    state.update(buckets)
    state["suppressed_ids"] = sorted(suppressed)
    return state


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


def _bucket_from_record_v2(record: Mapping[str, object], index: int) -> WeightBucketV2:
    raw_bucket = record.get("bucket")
    if isinstance(raw_bucket, str) and raw_bucket in _KIND_BUCKETS_V2.values():
        return raw_bucket  # type: ignore[return-value]
    raw_kind = record.get("kind")
    if isinstance(raw_kind, str):
        bucket = _KIND_BUCKETS_V2.get(raw_kind.strip().lower())
        if bucket is not None:
            return bucket
    raise ValueError(f"record {index} must include a supported v2 kind or bucket")


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


def _clean_runtime_state(
    state: Mapping[str, object],
    *,
    format_version: str = CHECKPOINT_FORMAT,
) -> dict[str, object]:
    allowed = (
        ALLOWED_STATE_KEYS_V2 if format_version == CHECKPOINT_FORMAT_V2 else ALLOWED_STATE_KEYS
    )
    unknown = sorted(set(state) - allowed)
    if unknown:
        raise ValueError(f"runtime state contains unsupported keys: {', '.join(unknown)}")

    clean: dict[str, object] = {}
    clean["bias"] = _coerce_number(state.get("bias", 0.5), "bias")
    weight_buckets: tuple[str, ...]
    if format_version == CHECKPOINT_FORMAT_V2:
        weight_buckets = (
            "summary_weights",
            "evidence_weights",
            "next_action_weights",
            "file_weights",
            "avoid_weights",
            "action_weights",
        )
        # Only carry v1-style buckets if the caller provided them, otherwise
        # omit them so the manifest stays compact.
        for bucket in weight_buckets:
            if bucket in state:
                clean[bucket] = _clean_weight_mapping(state[bucket], bucket)
        raw_suppressed = state.get("suppressed_ids", [])
        clean["suppressed_ids"] = _clean_suppressed_ids(raw_suppressed)
        return clean
    for bucket in ("action_weights", "file_weights", "evidence_weights"):
        clean[bucket] = _clean_weight_mapping(state.get(bucket, {}), bucket)
    return clean


def _clean_suppressed_ids(raw: object) -> list[str]:
    if isinstance(raw, str | bytes):
        raise ValueError("suppressed_ids must be a list of strings")
    if not isinstance(raw, Iterable):
        raise ValueError("suppressed_ids must be a list of strings")
    ids: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("suppressed_ids entries must be non-empty strings")
        ids.append(item.strip())
    return sorted(set(ids))


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
    "WeightBucket",
    "WeightBucketV2",
    "build_action_memory_checkpoint_state",
    "build_action_memory_checkpoint_state_v2",
    "write_action_memory_checkpoint",
]
