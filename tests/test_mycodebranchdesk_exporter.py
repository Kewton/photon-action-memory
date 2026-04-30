from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from photon_action_memory.training.exporters.mycodebranchdesk import (
    MyCodeBranchDeskExportOptions,
    export_mycodebranchdesk_sqlite,
)


def test_export_mycodebranchdesk_sqlite_writes_sanitized_labels(tmp_path: Path) -> None:
    db_path = tmp_path / "mycodebranchdesk.sqlite"
    out_path = tmp_path / "examples.jsonl"
    redaction_report_path = tmp_path / "redactions.json"
    _create_fixture_db(db_path)

    result = export_mycodebranchdesk_sqlite(
        db_path,
        out_path=out_path,
        redaction_report_path=redaction_report_path,
        options=MyCodeBranchDeskExportOptions(min_session_messages=3),
    )

    examples = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
    assert len(examples) == result.summary["counters"]["examples_written"]
    assert len(examples) >= 2

    test_example = _example_with_action(examples, "test")
    assert test_example["source"]["db_path_hash"]
    assert "db_path" not in test_example["source"]
    assert test_example["label"]["next_tool"] == "Bash"
    assert test_example["label"]["target_files"] == ["tests/test_app.py"]
    assert "tests/test_app.py" in test_example["label"]["useful_evidence"]
    assert test_example["text"]["sanitized_assistant"] == ""
    assert test_example["redaction"]["status"] == "sanitized"

    output_text = out_path.read_text(encoding="utf-8")
    assert str(db_path) not in output_text
    assert "/Users/alice/project" not in output_text
    assert "alice@example.com" not in output_text
    assert "abcdefghijklmnop" not in output_text
    assert "src/app.py" in output_text

    report = json.loads(redaction_report_path.read_text(encoding="utf-8"))
    assert report["absolute_path"] >= 1
    assert report["email"] >= 1
    assert report["secret_assignment"] >= 1


def _create_fixture_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE worktrees (
                id INTEGER PRIMARY KEY,
                name TEXT,
                path TEXT,
                repository_path TEXT,
                repository_name TEXT,
                initial_branch TEXT
            );
            CREATE TABLE chat_messages (
                id INTEGER PRIMARY KEY,
                worktree_id INTEGER,
                role TEXT,
                content TEXT,
                summary TEXT,
                timestamp INTEGER,
                log_file_name TEXT,
                request_id TEXT,
                message_type TEXT,
                prompt_data TEXT,
                cli_tool_id TEXT,
                archived INTEGER DEFAULT 0
            );
            """
        )
        conn.execute(
            """
            INSERT INTO worktrees (
                id, name, path, repository_path, repository_name, initial_branch
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "fixture-worktree",
                "/Users/alice/project",
                "/Users/alice/project",
                "fixture-repo",
                "main",
            ),
        )
        rows = [
            (
                1,
                1,
                "user",
                (
                    "Fix /Users/alice/project/src/app.py and contact alice@example.com. "
                    "token=abcdefghijklmnop"
                ),
                None,
                100,
                "raw.log",
                "req-1",
                "message",
                None,
                "codex",
                0,
            ),
            (
                2,
                1,
                "assistant",
                '<tool_call>{"name":"Read","input":{"file_path":"/Users/alice/project/src/app.py"}}</tool_call>',
                None,
                101,
                "raw.log",
                "req-2",
                "message",
                None,
                "codex",
                0,
            ),
            (
                3,
                1,
                "user",
                "Run the focused test for /Users/alice/project/tests/test_app.py",
                None,
                102,
                "raw.log",
                "req-3",
                "message",
                None,
                "codex",
                0,
            ),
            (
                4,
                1,
                "assistant",
                (
                    '<tool_call>{"name":"Bash","input":'
                    '{"cmd":"pytest tests/test_app.py"}}</tool_call> '
                    "completed /Users/alice/project/tests/test_app.py"
                ),
                None,
                103,
                "raw.log",
                "req-4",
                "message",
                None,
                "codex",
                0,
            ),
        ]
        conn.executemany(
            """
            INSERT INTO chat_messages (
                id,
                worktree_id,
                role,
                content,
                summary,
                timestamp,
                log_file_name,
                request_id,
                message_type,
                prompt_data,
                cli_tool_id,
                archived
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def _example_with_action(examples: list[dict[str, Any]], action: str) -> dict[str, Any]:
    for example in examples:
        if example["label"]["next_action"] == action:
            return example
    raise AssertionError(f"missing example with action {action!r}")
