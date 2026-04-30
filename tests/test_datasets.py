from __future__ import annotations

import json
from pathlib import Path

import pytest

from photon_action_memory import SCHEMA_VERSION
from photon_action_memory.training.datasets import (
    DatasetRecord,
    dataset_stats,
    make_dataset_record,
    read_jsonl,
    split_records,
    stable_example_id,
    write_jsonl,
    write_split_dataset,
)


def _fixture_records() -> list[DatasetRecord]:
    return [
        make_dataset_record(
            example_id="ex-1",
            source={
                "session_id": "s1",
                "tool_name": "shell",
                "artifacts": [{"path": "src/app.py"}],
            },
            task={"kind": "fix"},
            state={"command": "pytest tests/test_app.py"},
            label={"action": "run_tests", "target_files": ["src/app.py", "/tmp/build.log"]},
            quality={"score": 1.0},
            redaction={"report_id": "red-1", "counts": {"secret_assignment": 1}},
        ),
        make_dataset_record(
            example_id="ex-2",
            source={"session_id": "s2"},
            task={"kind": "edit"},
            state={"tool_name": "editor"},
            label={
                "action": "edit_file",
                "command": "python -m pytest",
                "target_files": ["README.md"],
            },
            quality={"score": 0.8},
            redaction={"report_id": "red-2", "email": 2},
        ),
        make_dataset_record(
            example_id="ex-3",
            source={"session_id": "s3", "tool_name": "browser"},
            task={"kind": "inspect"},
            state={},
            label={"action_type": "inspect", "target_file": "workspace/v0.1.0/04_work_plan.md"},
            quality={"score": 0.7},
            redaction={"report_id": "red-3", "counts": {}},
        ),
    ]


def test_dataset_record_has_required_jsonl_fields() -> None:
    record = _fixture_records()[0]

    assert tuple(record.as_dict()) == (
        "example_id",
        "schema_version",
        "source",
        "task",
        "state",
        "label",
        "quality",
        "redaction",
    )
    assert record.schema_version == SCHEMA_VERSION


def test_dataset_record_validation_requires_spec_fields() -> None:
    with pytest.raises(ValueError, match="redaction"):
        DatasetRecord.from_mapping(
            {
                "example_id": "ex-missing",
                "schema_version": SCHEMA_VERSION,
                "source": {},
                "task": {},
                "state": {},
                "label": {},
                "quality": {},
            }
        )


def test_stable_example_id_is_deterministic() -> None:
    body = {"label": {"action": "edit"}, "state": {"text": "safe"}}

    assert stable_example_id(body) == stable_example_id(
        {"state": {"text": "safe"}, "label": {"action": "edit"}}
    )


def test_jsonl_round_trip_preserves_redaction_report_link(tmp_path: Path) -> None:
    path = tmp_path / "dataset.jsonl"
    records = _fixture_records()

    write_jsonl(records, path)
    loaded = read_jsonl(path)

    assert loaded == records
    assert loaded[0].redaction["report_id"] == "red-1"


def test_split_records_is_deterministic_and_preserves_redaction() -> None:
    records = _fixture_records()

    first = split_records(records, ratios={"train": 1, "val": 1, "test": 1}, seed="fixture")
    second = split_records(
        list(reversed(records)),
        ratios={"train": 1, "val": 1, "test": 1},
        seed="fixture",
    )

    assert {name: [record.example_id for record in split] for name, split in first.items()} == {
        name: [record.example_id for record in split] for name, split in second.items()
    }
    report_ids = sorted(
        record.redaction["report_id"] for split in first.values() for record in split
    )
    assert report_ids == [
        "red-1",
        "red-2",
        "red-3",
    ]


def test_dataset_stats_counts_actions_tools_cli_files_and_redactions() -> None:
    stats = dataset_stats(_fixture_records())

    assert stats == {
        "total_examples": 3,
        "actions": {"edit_file": 1, "inspect": 1, "run_tests": 1},
        "tools": {"browser": 1, "editor": 1, "shell": 1},
        "cli": {"pytest": 1, "python": 1},
        "target_files": {
            "README.md": 1,
            "[ABS_PATH]/build.log": 1,
            "src/app.py": 1,
            "workspace/v0.1.0/04_work_plan.md": 1,
        },
        "target_file_total": 4,
        "redaction": {"email": 2, "secret_assignment": 1},
    }


def test_write_split_dataset_outputs_jsonl_and_stats(tmp_path: Path) -> None:
    records = _fixture_records()
    paths = write_split_dataset(
        records,
        tmp_path,
        ratios={"train": 1, "val": 1, "test": 1},
        seed="fixture",
    )

    assert set(paths) == {"train", "val", "test", "stats"}
    assert sum(len(read_jsonl(paths[name])) for name in ("train", "val", "test")) == 3
    assert json.loads(paths["stats"].read_text(encoding="utf-8"))["redaction"] == {
        "email": 2,
        "secret_assignment": 1,
    }
