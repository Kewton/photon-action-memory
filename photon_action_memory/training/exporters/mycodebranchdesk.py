"""MyCodeBranchDesk SQLite trajectory exporter."""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from photon_action_memory import SCHEMA_VERSION
from photon_action_memory.memory.sanitizer import sanitize_text_with_report
from photon_action_memory.training.datasets import (
    ExportStats,
    stable_hash,
    summarize_export_stats,
    write_jsonl,
    write_redaction_report,
)
from photon_action_memory.training.labels import (
    MAX_FILE_PATHS,
    MAX_TARGET_FILES,
    classify_next_action,
    dedupe_preserve_order,
    extract_file_paths,
    extract_tool_names,
    infer_useful_evidence,
    parse_prompt_data,
)

DEFAULT_TOOLS = ("claude", "codex")
MAX_RECENT_TOOLS = 12

Example = dict[str, Any]


@dataclass(frozen=True)
class MyCodeBranchDeskExportOptions:
    """Configuration for MyCodeBranchDesk dataset export."""

    tools: tuple[str, ...] = DEFAULT_TOOLS
    since: int | None = None
    until: int | None = None
    max_context_messages: int = 12
    max_content_chars: int = 12_000
    max_summary_chars: int = 2_000
    min_session_messages: int = 3
    include_copilot: bool = False
    include_raw_text: bool = False
    sample: int | None = None
    seed: int = 42


@dataclass(frozen=True)
class MyCodeBranchDeskExportResult:
    """Export result returned to callers and tests."""

    examples: list[Example]
    stats: ExportStats
    summary: dict[str, Any]


def export_mycodebranchdesk_sqlite(
    db_path: str | Path,
    *,
    out_path: str | Path | None = None,
    redaction_report_path: str | Path | None = None,
    options: MyCodeBranchDeskExportOptions | None = None,
) -> MyCodeBranchDeskExportResult:
    """Export sanitized JSONL examples from a MyCodeBranchDesk SQLite database."""
    opts = options or MyCodeBranchDeskExportOptions()
    resolved_db_path = Path(db_path).expanduser().resolve()
    stats = ExportStats()

    conn = connect_readonly(resolved_db_path)
    try:
        rows = load_messages(
            conn,
            tools=set(opts.tools),
            since=opts.since,
            until=opts.until,
            include_copilot=opts.include_copilot,
        )
    finally:
        conn.close()

    grouped = group_sessions(rows)
    examples = list(
        iter_examples(
            grouped,
            db_hash=stable_hash(str(resolved_db_path)),
            options=opts,
            stats=stats,
        )
    )
    examples = maybe_sample(examples, opts.sample, opts.seed)
    stats.counters["examples_written"] = len(examples)

    if out_path is not None:
        write_jsonl(out_path, examples)
    if redaction_report_path is not None:
        write_redaction_report(redaction_report_path, stats.redactions)

    return MyCodeBranchDeskExportResult(
        examples=examples,
        stats=stats,
        summary=summarize_export_stats(stats, output=out_path),
    )


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite database in read-only mode."""
    if not db_path.exists():
        msg = f"database not found: {db_path}"
        raise FileNotFoundError(msg)
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_messages(
    conn: sqlite3.Connection,
    *,
    tools: set[str],
    since: int | None,
    until: int | None,
    include_copilot: bool,
) -> list[sqlite3.Row]:
    """Load candidate chat rows from the MyCodeBranchDesk schema."""
    selected_tools = set(tools)
    if include_copilot:
        selected_tools.add("copilot")

    clauses = ["cm.archived = 0"]
    params: list[Any] = []
    if selected_tools:
        placeholders = ",".join("?" for _ in selected_tools)
        clauses.append(f"cm.cli_tool_id IN ({placeholders})")
        params.extend(sorted(selected_tools))
    if since is not None:
        clauses.append("cm.timestamp >= ?")
        params.append(since)
    if until is not None:
        clauses.append("cm.timestamp <= ?")
        params.append(until)

    where = " AND ".join(clauses)
    query = f"""
        SELECT
            cm.id,
            cm.worktree_id,
            cm.role,
            cm.content,
            cm.summary,
            cm.timestamp,
            cm.log_file_name,
            cm.request_id,
            cm.message_type,
            cm.prompt_data,
            cm.cli_tool_id,
            wt.name AS worktree_name,
            wt.path AS worktree_path,
            wt.repository_path AS repository_path,
            wt.repository_name AS repository_name,
            wt.initial_branch AS initial_branch
        FROM chat_messages cm
        LEFT JOIN worktrees wt ON wt.id = cm.worktree_id
        WHERE {where}
        ORDER BY cm.worktree_id, cm.cli_tool_id, cm.timestamp, cm.id
    """
    return list(conn.execute(query, params))


def group_sessions(rows: Iterable[sqlite3.Row]) -> dict[tuple[str, str], list[sqlite3.Row]]:
    """Group rows by worktree and CLI tool."""
    grouped: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        grouped[(_row_str(row, "worktree_id"), _row_str(row, "cli_tool_id"))].append(row)
    return dict(grouped)


def iter_examples(
    grouped: dict[tuple[str, str], list[sqlite3.Row]],
    *,
    db_hash: str,
    options: MyCodeBranchDeskExportOptions,
    stats: ExportStats,
) -> Iterable[Example]:
    """Yield sanitized training examples from grouped sessions."""
    for rows in grouped.values():
        stats.inc("sessions_seen")
        if not should_include_session(rows, options.min_session_messages):
            stats.inc("excluded_short_session")
            continue
        for idx, row in enumerate(rows):
            stats.inc("messages_seen")
            if _row_str(row, "role") != "assistant":
                continue
            stats.inc("assistant_candidates")
            context = rows[max(0, idx - options.max_context_messages) : idx]
            if not context:
                stats.inc("excluded_no_context")
                continue
            example = build_example(
                row=row,
                context=context,
                db_hash=db_hash,
                options=options,
                stats=stats,
            )
            if example is not None:
                yield example


def build_example(
    *,
    row: sqlite3.Row,
    context: list[sqlite3.Row],
    db_hash: str,
    options: MyCodeBranchDeskExportOptions,
    stats: ExportStats,
) -> Example | None:
    """Build one sanitized trajectory example or return None if signal is too weak."""
    roots = _workspace_roots(row)
    prompt_data = parse_prompt_data(_row_optional_str(row, "prompt_data"))
    content = _row_str(row, "content")
    context_text = summarize_context(
        context,
        roots=roots,
        max_chars=options.max_summary_chars,
        stats=stats,
    )
    sanitized_assistant = _sanitize_text(
        content,
        workspace_roots=roots,
        max_chars=options.max_content_chars,
        stats=stats,
    )
    latest_request = latest_user_request(
        context,
        stats=stats,
        roots=roots,
        max_chars=min(options.max_content_chars, 4_000),
    )
    tools = extract_tool_names(sanitized_assistant, prompt_data)
    files_from_context: list[str] = []
    for ctx_row in context:
        files_from_context.extend(
            extract_file_paths(
                _row_str(ctx_row, "content"),
                workspace_roots=roots,
            )
        )
    context_files = dedupe_preserve_order(files_from_context)[:MAX_FILE_PATHS]
    target_files = extract_file_paths(
        sanitized_assistant,
        workspace_roots=roots,
        limit=MAX_TARGET_FILES,
    )
    all_file_signal = dedupe_preserve_order([*context_files, *target_files])
    action = classify_next_action(tools, sanitized_assistant)

    has_tool_signal = bool(tools)
    has_file_signal = bool(all_file_signal)
    if not has_tool_signal and not has_file_signal and action == "answer":
        stats.inc("excluded_no_signal")
        return None

    confidence = score_confidence(
        has_tool_signal=has_tool_signal,
        has_file_signal=has_file_signal,
        action=action,
        target_files=target_files,
        context=context,
    )
    if confidence <= 0.0:
        stats.inc("excluded_zero_confidence")
        return None

    task_signature_source = latest_request or context_text or sanitized_assistant[:400]
    example = {
        "example_id": f"chatmsg_{_row_str(row, 'id')}",
        "schema_version": SCHEMA_VERSION,
        "task_type": "next_action",
        "source": {
            "db_path_hash": db_hash,
            "cli_tool_id": _row_optional_str(row, "cli_tool_id"),
            "worktree_id": _row_json_value(row, "worktree_id"),
            "repository_name": _row_optional_str(row, "repository_name"),
            "worktree_name": _row_optional_str(row, "worktree_name"),
            "initial_branch": _row_optional_str(row, "initial_branch"),
            "timestamp": _row_json_value(row, "timestamp"),
            "message_id": _row_json_value(row, "id"),
        },
        "task": {
            "latest_user_request": latest_request,
            "task_signature": stable_hash(task_signature_source),
            "mode_hint": infer_mode_hint(context, sanitized_assistant),
        },
        "state": {
            "recent_messages_summary": context_text,
            "touched_files": context_files[:12],
            "candidate_files": all_file_signal[:MAX_FILE_PATHS],
            "recent_errors": extract_recent_errors(context, roots, stats),
            "recent_tools": recent_tools_from_context(context)[-MAX_RECENT_TOOLS:],
        },
        "label": {
            "next_action": action,
            "next_tool": tools[0] if tools else None,
            "target_files": target_files,
            "useful_evidence": infer_useful_evidence(context_files, target_files),
            "should_replan": action == "replan",
            "outcome": infer_outcome(row, action),
        },
        "quality": {
            "has_tool_signal": has_tool_signal,
            "has_file_signal": has_file_signal,
            "is_success_like": None,
            "confidence": round(confidence, 3),
        },
        "redaction": {
            "status": "sanitized",
            "raw_text_included": options.include_raw_text,
        },
        "text": {
            "sanitized_prompt": context_text,
            "sanitized_assistant": sanitized_assistant if options.include_raw_text else "",
        },
    }
    stats.actions[action] += 1
    if tools:
        stats.tools[tools[0]] += 1
    cli_tool_id = _row_optional_str(row, "cli_tool_id")
    if cli_tool_id:
        stats.examples_by_cli[cli_tool_id] += 1
    stats.context_chars.append(len(context_text))
    stats.target_file_counts.append(len(target_files))
    return example


def latest_user_request(
    context: list[sqlite3.Row],
    *,
    stats: ExportStats,
    roots: list[str],
    max_chars: int,
) -> str:
    """Return the most recent sanitized user request from context."""
    for row in reversed(context):
        if _row_str(row, "role") == "user":
            return _sanitize_text(
                _row_str(row, "content"),
                workspace_roots=roots,
                max_chars=max_chars,
                stats=stats,
            )
    return ""


def summarize_context(
    context: list[sqlite3.Row],
    *,
    roots: list[str],
    max_chars: int,
    stats: ExportStats,
) -> str:
    """Render a compact sanitized context summary."""
    lines: list[str] = []
    for row in context:
        role = _row_str(row, "role") or "unknown"
        raw_text = _row_optional_str(row, "summary") or _row_str(row, "content")
        text = _sanitize_text(raw_text, workspace_roots=roots, max_chars=600, stats=stats)
        text = " ".join(text.split())
        if text:
            lines.append(f"{role}: {text}")
    rendered = "\n".join(lines)
    if len(rendered) > max_chars:
        stats.redactions["truncated_context"] += 1
        rendered = rendered[:max_chars] + "\n...[truncated]"
    return rendered


def recent_tools_from_context(context: list[sqlite3.Row]) -> list[str]:
    """Extract recent assistant tool names from prior messages."""
    tools: list[str] = []
    for row in context:
        if _row_str(row, "role") != "assistant":
            continue
        prompt_data = parse_prompt_data(_row_optional_str(row, "prompt_data"))
        tools.extend(extract_tool_names(_row_str(row, "content"), prompt_data))
    return dedupe_preserve_order(tools)


def extract_recent_errors(
    context: list[sqlite3.Row],
    roots: list[str],
    stats: ExportStats,
) -> list[str]:
    """Extract compact sanitized recent error snippets."""
    errors: list[str] = []
    for row in context[-8:]:
        text = _row_str(row, "content")
        lower = text.lower()
        if any(word in lower for word in ("error", "failed", "timeout", "エラー", "失敗")):
            safe = _sanitize_text(text, workspace_roots=roots, max_chars=300, stats=stats)
            safe = " ".join(safe.split())
            if safe:
                errors.append(safe)
    return errors[:4]


def infer_mode_hint(context: list[sqlite3.Row], assistant_text: str) -> str:
    """Infer a coarse plan/act mode hint."""
    text = "\n".join(_row_str(row, "content") for row in context[-4:]) + "\n" + assistant_text
    lower = text.lower()
    if "/plan" in lower or "plan mode" in lower or "計画" in text:
        return "plan"
    if any(word in lower for word in ("edit", "write", "apply_patch", "bash", "test")):
        return "act"
    return "unknown"


def infer_outcome(row: sqlite3.Row, action: str) -> str:
    """Infer a weak outcome signal from the assistant text."""
    content = _row_str(row, "content").lower()
    if any(word in content for word in ("error", "failed", "timeout", "失敗", "エラー")):
        return "failure_signal"
    if action in {"edit", "test", "build"} and any(
        word in content for word in ("passed", "success", "completed", "完了", "成功")
    ):
        return "success_signal"
    return "unknown"


def score_confidence(
    *,
    has_tool_signal: bool,
    has_file_signal: bool,
    action: str,
    target_files: list[str],
    context: list[sqlite3.Row],
) -> float:
    """Score exported labels so low-signal examples can be excluded."""
    score = 0.25
    if has_tool_signal:
        score += 0.35
    if has_file_signal:
        score += 0.2
    if target_files:
        score += 0.1
    if action != "answer":
        score += 0.05
    if any(_row_str(row, "role") == "user" for row in context):
        score += 0.05
    return min(score, 1.0)


def should_include_session(rows: list[sqlite3.Row], min_messages: int) -> bool:
    """Return whether a grouped session is large enough and user grounded."""
    return len(rows) >= min_messages and any(_row_str(row, "role") == "user" for row in rows)


def maybe_sample(examples: list[Example], sample: int | None, seed: int) -> list[Example]:
    """Return a deterministic sample of examples when requested."""
    if sample is None or sample >= len(examples):
        return examples
    rng = random.Random(seed)
    selected = rng.sample(examples, sample)
    selected.sort(key=lambda ex: (ex["source"]["timestamp"], ex["example_id"]))
    return selected


def _sanitize_text(
    text: str | None,
    *,
    workspace_roots: Iterable[str],
    max_chars: int,
    stats: ExportStats,
) -> str:
    result = sanitize_text_with_report(
        text,
        workspace_roots=workspace_roots,
        max_chars=max_chars,
    )
    stats.record_redactions(result.report.as_dict())
    return result.text


def _workspace_roots(row: sqlite3.Row) -> list[str]:
    return [
        _row_str(row, "worktree_path"),
        _row_str(row, "repository_path"),
        str(Path.cwd()),
    ]


def _row_str(row: sqlite3.Row, key: str) -> str:
    value = row[key]
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _row_optional_str(row: sqlite3.Row, key: str) -> str | None:
    value = row[key]
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _row_json_value(row: sqlite3.Row, key: str) -> str | int | float | None:
    value = row[key]
    if value is None or isinstance(value, str | int | float):
        return value
    return str(value)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export sanitized agent training examples from MyCodeBranchDesk SQLite"
    )
    parser.add_argument("--db", required=True, help="SQLite database path")
    parser.add_argument("--out", required=True, help="Output JSONL path")
    parser.add_argument("--tools", default=",".join(DEFAULT_TOOLS))
    parser.add_argument("--since", type=int, default=None)
    parser.add_argument("--until", type=int, default=None)
    parser.add_argument("--max-context-messages", type=int, default=12)
    parser.add_argument("--max-content-chars", type=int, default=12_000)
    parser.add_argument("--max-summary-chars", type=int, default=2_000)
    parser.add_argument("--min-session-messages", type=int, default=3)
    parser.add_argument("--include-copilot", action="store_true")
    parser.add_argument("--include-raw-text", action="store_true")
    parser.add_argument("--stats-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sample", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--redaction-report", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for module execution."""
    args = _parse_args(argv)
    sample = cast(int | None, args.sample)
    if args.dry_run and sample is None:
        sample = 20
    tools = tuple(tool.strip() for tool in str(args.tools).split(",") if tool.strip())
    options = MyCodeBranchDeskExportOptions(
        tools=tools,
        since=cast(int | None, args.since),
        until=cast(int | None, args.until),
        max_context_messages=cast(int, args.max_context_messages),
        max_content_chars=cast(int, args.max_content_chars),
        max_summary_chars=cast(int, args.max_summary_chars),
        min_session_messages=cast(int, args.min_session_messages),
        include_copilot=cast(bool, args.include_copilot),
        include_raw_text=cast(bool, args.include_raw_text),
        sample=sample,
        seed=cast(int, args.seed),
    )

    try:
        result = export_mycodebranchdesk_sqlite(
            cast(str, args.db),
            out_path=None if args.stats_only else cast(str, args.out),
            redaction_report_path=cast(str | None, args.redaction_report),
            options=options,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result.summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "MyCodeBranchDeskExportOptions",
    "MyCodeBranchDeskExportResult",
    "build_example",
    "connect_readonly",
    "export_mycodebranchdesk_sqlite",
    "group_sessions",
    "iter_examples",
    "load_messages",
    "main",
]
