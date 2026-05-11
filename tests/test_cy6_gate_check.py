from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cy6_gate_check.py"
SPEC = importlib.util.spec_from_file_location("cy6_gate_check", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
cy6_gate_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cy6_gate_check)


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


def _state_with_logs(
    tmp_path: Path,
    eval_records: list[dict[str, Any]],
    llm_events: list[dict[str, Any]],
) -> Path:
    session = tmp_path / "sessions" / "01900001-0000-7000-8000-000000000001"
    _write_jsonl(session / "logs" / "eval.jsonl", eval_records)
    _write_jsonl(session / "logs" / "llm-io.jsonl", llm_events)
    return tmp_path / "sessions"


def _eval_record(canary: int, final_outcome: str = "done") -> dict[str, Any]:
    return {
        "session_id": "s",
        "photon_canary": canary,
        "final_outcome": final_outcome,
        "photon_eval": {"prompt_adopted": canary > 0},
    }


def test_cy6_gate_report_ready_when_all_conditions_pass(tmp_path: Path) -> None:
    eval_records = [_eval_record(500) for _ in range(50)] + [_eval_record(0) for _ in range(50)]
    llm_events = [
        {
            "event": "agent.photon_context_pack.completed",
            "payload": {"failed": False, "injected_bytes": 320, "truncated": False},
        },
        {
            "event": "agent.photon_evaluate.completed",
            "payload": {"failed": False},
        },
        {
            "event": "ollama.generate.request",
            "payload": {
                "messages": [
                    {
                        "content": (
                            "[Photon External Memory]\n"
                            "- project codename is heliograph\n"
                            "End Photon External Memory"
                        )
                    }
                ]
            },
        },
    ]
    state_dir = _state_with_logs(tmp_path, eval_records, llm_events)

    report = cy6_gate_check.build_gate_report(state_dir)

    assert report["ready_for_rollout"] is True
    assert {gate["status"] for gate in report["gates"]} == {"ok"}
    assert report["stats"]["photon_eval_turns"] == 100
    assert report["stats"]["success_delta_pp"] == 0.0


def test_cy6_gate_report_blocks_on_raw_marker_fail_open_and_prompt_size(tmp_path: Path) -> None:
    eval_records = [_eval_record(500) for _ in range(10)] + [_eval_record(0) for _ in range(10)]
    llm_events = [
        {
            "event": "agent.photon_context_pack.completed",
            "payload": {"failed": True, "injected_bytes": 9000, "truncated": True},
        },
        {
            "event": "ollama.generate.request",
            "payload": {
                "messages": [
                    {
                        "content": (
                            "[Photon External Memory]\n"
                            "stdout: raw command output\n"
                            "End Photon External Memory"
                        )
                    }
                ]
            },
        },
    ]
    state_dir = _state_with_logs(tmp_path, eval_records, llm_events)

    report = cy6_gate_check.build_gate_report(state_dir)
    statuses = {gate["id"]: gate["status"] for gate in report["gates"]}

    assert report["ready_for_rollout"] is False
    assert statuses["CY6-1"] == "ng"
    assert statuses["CY6-2"] == "ng"
    assert statuses["CY6-3"] == "ng"
    assert statuses["CY6-4"] == "ng"
    assert statuses["CY6-5"] == "manual"
