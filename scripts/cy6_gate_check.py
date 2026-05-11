#!/usr/bin/env python3
"""CY-6: combined rollout gate check for Anvil Photon live injection.

The script reads Anvil session logs and reports only aggregate gate metrics.
It does not print raw prompts, tool output, or user text.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SUCCESS_OUTCOMES = {"done"}
RAW_MARKERS = (
    "stdout",
    "stderr",
    "raw_output",
    "build_log",
    "tool_output",
    "command output",
)


def _default_state_root() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"),
        ".local",
        "state",
    )
    return Path(xdg) / "anvil" / "sessions"


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    yield value
    except OSError:
        return


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)


def _photon_sections(text: str) -> Iterable[str]:
    header = "Photon External Memory"
    footer = "End Photon External Memory"
    start = 0
    while True:
        header_idx = text.find(header, start)
        if header_idx < 0:
            return
        footer_idx = text.find(footer, header_idx)
        if footer_idx < 0:
            yield text[header_idx:]
            return
        yield text[header_idx:footer_idx]
        start = footer_idx + len(footer)


def _count_raw_marker_hits(payload: dict[str, Any]) -> int:
    hits = 0
    for text in _walk_strings(payload):
        for section in _photon_sections(text):
            lowered = section.lower()
            if any(marker in lowered for marker in RAW_MARKERS):
                hits += 1
    return hits


def _collect(state_dir: Path) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "total_eval_records": 0,
        "photon_eval_turns": 0,
        "prompt_adopted_turns": 0,
        "sampled_total": 0,
        "sampled_success": 0,
        "unsampled_total": 0,
        "unsampled_success": 0,
        "photon_operation_events": 0,
        "fail_open_events": 0,
        "max_injected_bytes": 0,
        "prompt_truncated_events": 0,
        "raw_marker_hits": 0,
        "raw_tool_tokens_in_prompt": 0,
    }
    if not state_dir.exists():
        return stats

    for session_dir in sorted(p for p in state_dir.iterdir() if p.is_dir()):
        eval_log = session_dir / "logs" / "eval.jsonl"
        for record in _iter_jsonl(eval_log):
            stats["total_eval_records"] += 1
            photon_eval = record.get("photon_eval")
            if photon_eval is not None:
                stats["photon_eval_turns"] += 1
                if isinstance(photon_eval, dict) and photon_eval.get("prompt_adopted") is True:
                    stats["prompt_adopted_turns"] += 1

            sampled = int(record.get("photon_canary") or 0) > 0
            group_total = "sampled_total" if sampled else "unsampled_total"
            group_success = "sampled_success" if sampled else "unsampled_success"
            stats[group_total] += 1
            if record.get("final_outcome") in SUCCESS_OUTCOMES:
                stats[group_success] += 1

        llm_log = session_dir / "logs" / "llm-io.jsonl"
        for event in _iter_jsonl(llm_log):
            name = str(event.get("event") or "")
            payload = event.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            if name.startswith("agent.photon") and name.endswith(".completed"):
                stats["photon_operation_events"] += 1
                if payload.get("failed") is True:
                    stats["fail_open_events"] += 1
            if name == "agent.photon_context_pack.completed":
                injected = payload.get("injected_bytes")
                if isinstance(injected, int):
                    stats["max_injected_bytes"] = max(stats["max_injected_bytes"], injected)
                if payload.get("truncated") is True:
                    stats["prompt_truncated_events"] += 1
                raw_tokens = payload.get("raw_tool_tokens_in_prompt")
                if isinstance(raw_tokens, int):
                    stats["raw_tool_tokens_in_prompt"] += raw_tokens
            if name in {"ollama.generate.request", "ollama.chat.request"}:
                stats["raw_marker_hits"] += _count_raw_marker_hits(payload)

    return stats


def _rate(success: int, total: int) -> float | None:
    if total == 0:
        return None
    return round(success / total * 100.0, 1)


def _status(ok: bool, reason: str | None = None) -> dict[str, Any]:
    return {"status": "ok" if ok else "ng", "reason": reason}


def build_gate_report(
    state_dir: Path,
    *,
    min_eval_turns: int = 100,
    max_fail_open_rate: float = 0.05,
    max_prompt_bytes: int = 8192,
    max_success_regression_pp: float = 5.0,
    min_group_turns: int = 20,
) -> dict[str, Any]:
    stats = _collect(state_dir)
    operation_events = stats["photon_operation_events"]
    fail_open_rate = (
        round(stats["fail_open_events"] / operation_events, 4) if operation_events else 0.0
    )
    sampled_rate = _rate(stats["sampled_success"], stats["sampled_total"])
    unsampled_rate = _rate(stats["unsampled_success"], stats["unsampled_total"])
    success_delta_pp = (
        round(sampled_rate - unsampled_rate, 1)
        if sampled_rate is not None and unsampled_rate is not None
        else None
    )

    raw_signal = stats["raw_tool_tokens_in_prompt"] + stats["raw_marker_hits"]
    gates = []

    ok = stats["photon_eval_turns"] >= min_eval_turns
    gates.append({
        "id": "CY6-1",
        "label": "minimum eval turns",
        "value": f"{stats['photon_eval_turns']}/{min_eval_turns}",
        **_status(ok, None if ok else "not enough photon_eval turns"),
    })

    ok = fail_open_rate <= max_fail_open_rate
    gates.append({
        "id": "CY6-2",
        "label": "fail-open incident rate",
        "value": fail_open_rate,
        **_status(ok, None if ok else f"fail_open_rate>{max_fail_open_rate}"),
    })

    ok = raw_signal == 0
    gates.append({
        "id": "CY6-3",
        "label": "raw token / marker leakage",
        "value": raw_signal,
        **_status(ok, None if ok else "raw prompt marker detected"),
    })

    ok = stats["max_injected_bytes"] <= max_prompt_bytes and stats["prompt_truncated_events"] == 0
    gates.append({
        "id": "CY6-4",
        "label": "prompt size",
        "value": {
            "max_injected_bytes": stats["max_injected_bytes"],
            "prompt_truncated_events": stats["prompt_truncated_events"],
        },
        **_status(ok, None if ok else "prompt size exceeded or truncation observed"),
    })

    enough_groups = (
        stats["sampled_total"] >= min_group_turns
        and stats["unsampled_total"] >= min_group_turns
    )
    if not enough_groups:
        gates.append({
            "id": "CY6-5",
            "label": "success-rate regression",
            "status": "manual",
            "value": {
                "sampled_total": stats["sampled_total"],
                "unsampled_total": stats["unsampled_total"],
            },
            "reason": f"need at least {min_group_turns} turns in each group",
        })
    else:
        ok = success_delta_pp is not None and success_delta_pp >= -max_success_regression_pp
        gates.append({
            "id": "CY6-5",
            "label": "success-rate regression",
            "status": "ok" if ok else "ng",
            "value": {
                "sampled_success_rate": sampled_rate,
                "unsampled_success_rate": unsampled_rate,
                "delta_pp": success_delta_pp,
            },
            "reason": None if ok else f"delta_pp < -{max_success_regression_pp}",
        })

    ready = all(g["status"] == "ok" for g in gates)
    return {
        "schema_version": "cy6-gate.v1",
        "state_dir": str(state_dir),
        "ready_for_rollout": ready,
        "stats": {
            **stats,
            "fail_open_rate": fail_open_rate,
            "sampled_success_rate": sampled_rate,
            "unsampled_success_rate": unsampled_rate,
            "success_delta_pp": success_delta_pp,
        },
        "gates": gates,
    }


def _print_text(report: dict[str, Any]) -> None:
    print("CY-6 Photon Canary Gate Check")
    print(f"state_dir: {report['state_dir']}")
    print("")
    for gate in report["gates"]:
        status = gate["status"].upper()
        line = f"[{status}] {gate['id']} {gate['label']}: {gate['value']}"
        reason = gate.get("reason")
        if reason:
            line += f" ({reason})"
        print(line)
    print("")
    print("Rollout READY" if report["ready_for_rollout"] else "Rollout BLOCKED")


def main() -> int:
    parser = argparse.ArgumentParser(description="CY-6 Photon canary gate check")
    parser.add_argument("--state-dir", type=Path, default=_default_state_root())
    parser.add_argument("--min-eval-turns", type=int, default=100)
    parser.add_argument("--max-fail-open-rate", type=float, default=0.05)
    parser.add_argument("--max-prompt-bytes", type=int, default=8192)
    parser.add_argument("--max-success-regression-pp", type=float, default=5.0)
    parser.add_argument("--min-group-turns", type=int, default=20)
    parser.add_argument("--json", action="store_true", dest="json_out")
    args = parser.parse_args()

    report = build_gate_report(
        args.state_dir,
        min_eval_turns=args.min_eval_turns,
        max_fail_open_rate=args.max_fail_open_rate,
        max_prompt_bytes=args.max_prompt_bytes,
        max_success_regression_pp=args.max_success_regression_pp,
        min_group_turns=args.min_group_turns,
    )
    if args.json_out:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_text(report)
    return 0 if report["ready_for_rollout"] else 1


if __name__ == "__main__":
    sys.exit(main())
