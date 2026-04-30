"""Dataset JSONL, deterministic split, and stats utilities."""

from __future__ import annotations

import hashlib
import json
import shlex
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import floor
from pathlib import Path
from typing import Any, Self, cast

from photon_action_memory import SCHEMA_VERSION
from photon_action_memory.memory.sanitizer import filter_safe_path_candidates

JsonObject = dict[str, Any]

REQUIRED_RECORD_FIELDS = (
    "example_id",
    "schema_version",
    "source",
    "task",
    "state",
    "label",
    "quality",
    "redaction",
)
SPLIT_NAMES = ("train", "val", "test")
DEFAULT_SPLIT_RATIOS = {"train": 0.8, "val": 0.1, "test": 0.1}
DEFAULT_SPLIT_SEED = "photon-action-memory.dataset.v1"


@dataclass(frozen=True)
class DatasetRecord:
    """One sanitized trajectory example in the dataset JSONL spec."""

    example_id: str
    schema_version: str
    source: JsonObject
    task: JsonObject
    state: JsonObject
    label: JsonObject
    quality: JsonObject
    redaction: JsonObject

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Self:
        """Validate and copy a JSON object into a dataset record."""
        missing = [field for field in REQUIRED_RECORD_FIELDS if field not in value]
        if missing:
            msg = f"dataset record missing required fields: {', '.join(missing)}"
            raise ValueError(msg)

        example_id = value["example_id"]
        schema_version = value["schema_version"]
        if not isinstance(example_id, str) or not example_id:
            msg = "dataset record example_id must be a non-empty string"
            raise TypeError(msg)
        if not isinstance(schema_version, str) or not schema_version:
            msg = "dataset record schema_version must be a non-empty string"
            raise TypeError(msg)

        return cls(
            example_id=example_id,
            schema_version=schema_version,
            source=_required_object(value, "source"),
            task=_required_object(value, "task"),
            state=_required_object(value, "state"),
            label=_required_object(value, "label"),
            quality=_required_object(value, "quality"),
            redaction=_required_object(value, "redaction"),
        )

    def as_dict(self) -> JsonObject:
        """Return a JSON-safe object preserving the dataset spec field order."""
        return {
            "example_id": self.example_id,
            "schema_version": self.schema_version,
            "source": dict(self.source),
            "task": dict(self.task),
            "state": dict(self.state),
            "label": dict(self.label),
            "quality": dict(self.quality),
            "redaction": dict(self.redaction),
        }


def make_dataset_record(
    *,
    source: Mapping[str, Any],
    task: Mapping[str, Any],
    state: Mapping[str, Any],
    label: Mapping[str, Any],
    quality: Mapping[str, Any] | None = None,
    redaction: Mapping[str, Any] | None = None,
    example_id: str | None = None,
    schema_version: str = SCHEMA_VERSION,
) -> DatasetRecord:
    """Create a dataset record, deriving a stable ID when one is not supplied."""
    record_body = {
        "schema_version": schema_version,
        "source": dict(source),
        "task": dict(task),
        "state": dict(state),
        "label": dict(label),
        "quality": dict(quality or {}),
        "redaction": dict(redaction or {}),
    }
    resolved_id = example_id or stable_example_id(record_body)
    return DatasetRecord.from_mapping({"example_id": resolved_id, **record_body})


def stable_example_id(value: Mapping[str, Any]) -> str:
    """Return a deterministic example ID for a JSON-like record body."""
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"ex-{digest[:16]}"


def write_jsonl(records: Iterable[DatasetRecord], path: str | Path) -> None:
    """Write dataset records as UTF-8 JSONL."""
    rows = [
        json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=False, separators=(",", ":"))
        for record in records
    ]
    Path(path).write_text(("\n".join(rows) + "\n") if rows else "", encoding="utf-8")


def read_jsonl(path: str | Path) -> list[DatasetRecord]:
    """Read dataset records from UTF-8 JSONL."""
    records: list[DatasetRecord] = []
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            msg = f"dataset JSONL line {line_number} must be a JSON object"
            raise TypeError(msg)
        records.append(DatasetRecord.from_mapping(cast(JsonObject, value)))
    return records


def split_records(
    records: Sequence[DatasetRecord],
    *,
    ratios: Mapping[str, float] | None = None,
    seed: str = DEFAULT_SPLIT_SEED,
) -> dict[str, list[DatasetRecord]]:
    """Create a deterministic train / val / test split."""
    split_ratios = dict(DEFAULT_SPLIT_RATIOS if ratios is None else ratios)
    counts = _split_counts(len(records), split_ratios)
    sorted_records = sorted(records, key=lambda record: _split_sort_key(record, seed))

    splits: dict[str, list[DatasetRecord]] = {name: [] for name in SPLIT_NAMES}
    offset = 0
    for name in SPLIT_NAMES:
        count = counts[name]
        splits[name] = sorted_records[offset : offset + count]
        offset += count
    return splits


def write_split_dataset(
    records: Sequence[DatasetRecord],
    output_dir: str | Path,
    *,
    ratios: Mapping[str, float] | None = None,
    seed: str = DEFAULT_SPLIT_SEED,
) -> dict[str, Path]:
    """Write train / val / test JSONL files and per-split stats."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    splits = split_records(records, ratios=ratios, seed=seed)
    paths: dict[str, Path] = {}

    for name, split_records_ in splits.items():
        split_path = destination / f"{name}.jsonl"
        write_jsonl(split_records_, split_path)
        paths[name] = split_path
        write_stats(split_records_, destination / f"{name}.stats.json")

    write_stats(records, destination / "dataset.stats.json")
    paths["stats"] = destination / "dataset.stats.json"
    return paths


def write_stats(records: Sequence[DatasetRecord], path: str | Path) -> None:
    """Write aggregate dataset stats as pretty JSON."""
    Path(path).write_text(
        json.dumps(dataset_stats(records), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def dataset_stats(records: Sequence[DatasetRecord]) -> JsonObject:
    """Return aggregate stats for actions, tools, CLI commands, files, and redactions."""
    action_counts: Counter[str] = Counter()
    tool_counts: Counter[str] = Counter()
    cli_counts: Counter[str] = Counter()
    target_file_counts: Counter[str] = Counter()
    redaction_counts: Counter[str] = Counter()

    for record in records:
        action = _first_string(
            record.label.get("action"),
            record.label.get("action_type"),
            record.label.get("next_action"),
            record.task.get("action"),
        )
        if action is not None:
            action_counts[action] += 1

        tool = _first_string(
            record.label.get("tool"),
            record.label.get("tool_name"),
            record.state.get("tool_name"),
            record.source.get("tool_name"),
        )
        if tool is not None:
            tool_counts[tool] += 1

        command = _first_string(
            record.label.get("cli"),
            record.label.get("command"),
            record.state.get("cli"),
            record.state.get("command"),
        )
        if command is not None:
            cli_counts[_command_name(command)] += 1

        target_file_counts.update(_target_files(record))
        redaction_counts.update(_redaction_counts(record.redaction))

    return {
        "total_examples": len(records),
        "actions": dict(sorted(action_counts.items())),
        "tools": dict(sorted(tool_counts.items())),
        "cli": dict(sorted(cli_counts.items())),
        "target_files": dict(sorted(target_file_counts.items())),
        "target_file_total": sum(target_file_counts.values()),
        "redaction": dict(sorted(redaction_counts.items())),
    }


def _required_object(value: Mapping[str, Any], key: str) -> JsonObject:
    child = value[key]
    if not isinstance(child, dict):
        msg = f"dataset record {key} must be a JSON object"
        raise TypeError(msg)
    return dict(cast(JsonObject, child))


def _split_sort_key(record: DatasetRecord, seed: str) -> tuple[str, str]:
    digest = hashlib.sha256(f"{seed}\0{record.example_id}".encode()).hexdigest()
    return digest, record.example_id


def _split_counts(total: int, ratios: Mapping[str, float]) -> dict[str, int]:
    extra = sorted(set(ratios) - set(SPLIT_NAMES))
    missing = [name for name in SPLIT_NAMES if name not in ratios]
    if missing or extra:
        msg = "split ratios must contain exactly train, val, and test"
        raise ValueError(msg)
    if any(ratio < 0 for ratio in ratios.values()):
        msg = "split ratios must be non-negative"
        raise ValueError(msg)

    ratio_total = sum(ratios.values())
    if ratio_total <= 0:
        msg = "at least one split ratio must be positive"
        raise ValueError(msg)

    raw_counts = {name: (ratios[name] / ratio_total) * total for name in SPLIT_NAMES}
    counts = {name: floor(raw_counts[name]) for name in SPLIT_NAMES}
    remaining = total - sum(counts.values())
    remainders = sorted(
        SPLIT_NAMES,
        key=lambda name: (raw_counts[name] - counts[name], -SPLIT_NAMES.index(name)),
        reverse=True,
    )
    for name in remainders[:remaining]:
        counts[name] += 1
    return counts


def _first_string(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _command_name(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    return parts[0] if parts else command


def _target_files(record: DatasetRecord) -> list[str]:
    candidates: list[str] = []
    for value in (
        record.label.get("target_files"),
        record.label.get("target_file"),
        record.state.get("target_files"),
        record.source.get("target_files"),
        record.source.get("artifacts"),
    ):
        candidates.extend(_path_candidates(value))
    return filter_safe_path_candidates(candidates)


def _path_candidates(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        path = value.get("path")
        return [path] if isinstance(path, str) else []
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        candidates: list[str] = []
        for child in value:
            candidates.extend(_path_candidates(child))
        return candidates
    return []


def _redaction_counts(redaction: Mapping[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    nested_counts = redaction.get("counts")
    if isinstance(nested_counts, Mapping):
        counts.update(_integer_items(nested_counts))
    counts.update(_integer_items(redaction))
    return counts


def _integer_items(value: Mapping[str, object]) -> dict[str, int]:
    return {
        str(key): child
        for key, child in value.items()
        if isinstance(child, int) and not isinstance(child, bool)
    }
