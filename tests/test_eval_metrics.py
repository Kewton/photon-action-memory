from __future__ import annotations

import json
from pathlib import Path

import pytest

from photon_action_memory.eval.metrics import build_metrics_report
from photon_action_memory.eval.runner import run_eval, run_fixture

FIXED_FIXTURE = [
    {
        "request_id": "turn-001",
        "suggestions": [
            {"kind": "read", "target": "src/session.py", "evidence_ids": ["evt-read"]},
            {"kind": "test", "command": "pytest tests/test_session.py"},
        ],
        "actual_next_action": {"kind": "read", "target": "src/session.py"},
        "actual_target_file": "src/session.py",
        "useful_evidence_ids": ["evt-read"],
        "warnings": [{"kind": "repeat_failure"}],
        "repeated_exploration_occurred": True,
        "outcome": "accepted",
        "latency_ms": 100,
        "sidecar_status": "ok",
        "raw_log": "this raw field must be ignored",
    },
    {
        "request_id": "turn-002",
        "suggestions": [
            {"kind": "search", "query": "unrelated"},
            {"kind": "edit", "target": "src/api.py", "evidence_ids": ["evt-wrong"]},
        ],
        "actual_next_action": {"kind": "edit", "target": "src/api.py"},
        "actual_target_file": "src/api.py",
        "useful_evidence_ids": ["evt-api"],
        "outcome": "ignored",
        "latency_ms": 180,
        "sidecar_status": "ok",
    },
    {
        "request_id": "turn-003",
        "suggestions": [
            {"kind": "search", "query": "previous failure"},
            {"kind": "answer"},
        ],
        "actual_next_action": {"kind": "answer"},
        "warnings": [{"kind": "repeat_failure"}],
        "repeated_exploration_occurred": False,
        "outcome": "fail_open",
        "latency_ms": 420,
        "sidecar_status": "timeout",
    },
]


def test_fixed_fixture_generates_expected_metrics() -> None:
    report = build_metrics_report(FIXED_FIXTURE, top_k=2)

    assert report.total_records == 3
    assert report.next_action_top_k == 2
    assert report.evaluated_next_action_records == 3
    assert report.next_action_hits == 3
    assert report.next_action_top_k_accuracy == 1.0
    assert report.evaluated_target_file_records == 2
    assert report.target_file_hits == 2
    assert report.target_file_hit_rate == 1.0
    assert report.evaluated_useful_evidence_records == 2
    assert report.useful_evidence_hits == 1
    assert report.useful_evidence_hit_rate == 0.5
    assert report.repeated_exploration_warnings == 2
    assert report.repeated_exploration_warning_true_positives == 1
    assert report.repeated_exploration_warning_precision == 0.5
    assert report.fail_open_incident_count == 1
    assert report.latency_sample_count == 3
    assert report.suggest_latency_p50_ms == 180
    assert report.suggest_latency_p95_ms == 420
    assert report.sidecar_status_counts == {"ok": 2, "timeout": 1}
    assert report.outcome_counts == {"accepted": 1, "fail_open": 1, "ignored": 1}


def test_runner_writes_only_aggregate_summary(tmp_path: Path) -> None:
    output_path = tmp_path / "metrics.json"

    report = run_eval(FIXED_FIXTURE, top_k=2, output_path=output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload == report.model_dump(mode="json")
    assert "total_records" in payload
    assert "next_action_top_k_accuracy" in payload
    assert "records" not in payload
    assert "suggestions" not in payload
    assert "actual_next_action" not in payload
    assert "request_id" not in payload
    assert "raw_log" not in payload


def test_runner_loads_json_fixture_object(tmp_path: Path) -> None:
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps({"records": FIXED_FIXTURE}), encoding="utf-8")

    report = run_fixture(fixture_path, top_k=1)

    assert report.next_action_hits == 1
    assert report.next_action_top_k_accuracy == pytest.approx(1 / 3)
