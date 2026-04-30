#!/usr/bin/env python3
"""Small CommandMate adapter for Codex orchestration.

This helper keeps command construction and JSON parsing testable. It does not
own orchestration policy; `scripts/codex_orchestrate.py` decides when to use it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class WorktreeSession:
    id: str
    path: str
    status: str
    is_processing: bool


def parse_worktrees(payload: str) -> list[WorktreeSession]:
    raw = json.loads(payload)
    items = raw.get("worktrees", raw if isinstance(raw, list) else [])
    sessions: list[WorktreeSession] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        session_status = item.get("sessionStatusByCli", {})
        codex_status = {}
        if isinstance(session_status, dict):
            codex_status = (
                session_status.get("codex")
                or session_status.get("default")
                or next(iter(session_status.values()), {})
            )
        sessions.append(
            WorktreeSession(
                id=str(item.get("id") or item.get("name") or ""),
                path=str(item.get("path") or item.get("worktreePath") or ""),
                status=str(item.get("status") or item.get("state") or ""),
                is_processing=bool(
                    item.get("isProcessing")
                    or (
                        codex_status.get("isProcessing")
                        if isinstance(codex_status, dict)
                        else False
                    )
                ),
            )
        )
    return [session for session in sessions if session.id]


def build_send_command(
    worktree_id: str,
    message: str,
    *,
    agent: str = "",
    auto_yes: bool = True,
    duration: str = "3h",
) -> list[str]:
    cmd = ["commandmatedev", "send", worktree_id, message]
    if agent:
        cmd.extend(["--agent", agent])
    if auto_yes:
        cmd.append("--auto-yes")
    if duration:
        cmd.extend(["--duration", duration])
    return cmd


def command_to_display(cmd: list[str]) -> str:
    return " ".join(cmd)


def list_sessions() -> list[WorktreeSession]:
    completed = subprocess.run(
        ["commandmatedev", "ls", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_worktrees(completed.stdout)


def send_message(worktree_id: str, message: str, *, agent: str = "", duration: str = "3h") -> None:
    subprocess.run(
        build_send_command(worktree_id, message, agent=agent, duration=duration),
        check=True,
    )


def capture(worktree_id: str, *, agent: str = "") -> str:
    cmd = ["commandmatedev", "capture", worktree_id]
    if agent:
        cmd.extend(["--agent", agent])
    cmd.append("--json")
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return completed.stdout


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    send = sub.add_parser("send")
    send.add_argument("worktree_id")
    send.add_argument("message")
    send.add_argument("--agent", default="")
    send.add_argument("--duration", default="3h")
    send.add_argument("--dry-run", action="store_true")
    cap = sub.add_parser("capture")
    cap.add_argument("worktree_id")
    cap.add_argument("--agent", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "list":
        for session in list_sessions():
            print(f"{session.id}\t{session.status}\t{session.is_processing}\t{session.path}")
        return 0
    if args.command == "send":
        cmd = build_send_command(
            args.worktree_id,
            args.message,
            agent=args.agent,
            duration=args.duration,
        )
        if args.dry_run:
            print(command_to_display(cmd))
        else:
            subprocess.run(cmd, check=True)
        return 0
    if args.command == "capture":
        print(capture(args.worktree_id, agent=args.agent))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
