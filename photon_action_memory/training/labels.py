"""Action label utilities for exported agent trajectories."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from photon_action_memory.memory.sanitizer import (
    filter_safe_path_candidates,
    normalize_absolute_paths,
)

MAX_FILE_PATHS = 24
MAX_TARGET_FILES = 8

TOOL_JSON_RE = re.compile(
    r"<(?:anvil_)?tool_call>\s*(\{.*?\})\s*</(?:anvil_)?tool_call>",
    re.DOTALL,
)
TOOL_NAME_RE = re.compile(
    r"\b(Read|Grep|Glob|Bash|Edit|Write|ApplyPatch|apply_patch|Shell|exec_command)\b",
    re.IGNORECASE,
)
FILE_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])"
    r"([A-Za-z0-9_./@+\-]+"
    r"\.(?:rs|py|ts|tsx|js|jsx|md|json|toml|yaml|yml|sh|html|css|go|java|kt|swift|c|cc|cpp|h|hpp|sql))"
)

ACTION_BY_TOOL = {
    "read": "read",
    "grep": "search",
    "glob": "discover",
    "bash": "shell",
    "shell": "shell",
    "exec_command": "shell",
    "edit": "edit",
    "write": "edit",
    "applypatch": "edit",
    "apply_patch": "edit",
}


def parse_prompt_data(raw: str | None) -> dict[str, Any] | None:
    """Parse MyCodeBranchDesk prompt metadata when it is a JSON object."""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def extract_tool_names(text: str | None, prompt_data: Mapping[str, Any] | None = None) -> list[str]:
    """Extract normalized tool names from assistant text and prompt metadata."""
    tools: list[str] = []
    for match in TOOL_JSON_RE.finditer(text or ""):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        name = payload.get("name")
        if isinstance(name, str):
            tools.append(name)

    tools.extend(match.group(1) for match in TOOL_NAME_RE.finditer(text or ""))

    if prompt_data:
        prompt_type = str(prompt_data.get("type") or "").strip().lower()
        if prompt_type in {"input", "multiple_choice", "confirmation"}:
            tools.append("AskUser")
        status = str(prompt_data.get("status") or "").lower()
        if status in {"pending", "answered"} and "question" in prompt_data:
            tools.append("AskUser")

    return dedupe_preserve_order(normalize_tool_name(tool) for tool in tools if tool)


def normalize_tool_name(name: str) -> str:
    """Normalize equivalent tool spellings into stable training labels."""
    collapsed = re.sub(r"[^A-Za-z_]", "", name).strip()
    if not collapsed:
        return ""
    mapping = {
        "applypatch": "ApplyPatch",
        "exec_command": "Bash",
        "Shell": "Bash",
        "AskUser": "AskUser",
    }
    return mapping.get(collapsed, collapsed[:1].upper() + collapsed[1:])


def classify_next_action(tools: list[str], text: str | None) -> str:
    """Classify the next action label from tool signal and assistant text."""
    if tools:
        first = tools[0]
        if first == "AskUser":
            return "ask_user"
        action = ACTION_BY_TOOL.get(first.lower())
        if action:
            if action == "shell":
                return classify_shell_action(text)
            return action

    lower = (text or "").lower()
    if any(word in lower for word in ("replan", "plan update", "計画")):
        return "replan"
    if any(word in lower for word in ("test", "pytest", "cargo test", "npm test")):
        return "test"
    return "answer"


def classify_shell_action(text: str | None) -> str:
    """Classify shell-like tool calls into more useful action labels."""
    lower = (text or "").lower()
    if any(cmd in lower for cmd in ("cargo test", "pytest", "npm test", "pnpm test", "yarn test")):
        return "test"
    if any(cmd in lower for cmd in ("cargo build", "npm run build", "pnpm build", "yarn build")):
        return "build"
    if any(cmd in lower for cmd in ("rg ", "grep ", "find ", "ls ")):
        return "search"
    if any(cmd in lower for cmd in ("git diff", "git status", "git show")):
        return "inspect"
    return "shell"


def extract_file_paths(
    text: str | None,
    *,
    workspace_roots: Iterable[str] = (),
    limit: int = MAX_FILE_PATHS,
) -> list[str]:
    """Extract safe, normalized file path labels from text."""
    safe_text = normalize_absolute_paths(text or "", workspace_roots=workspace_roots)
    candidates = [clean_path(match.group(1)) for match in FILE_RE.finditer(safe_text)]
    safe_candidates = filter_safe_path_candidates(candidates, workspace_roots=workspace_roots)
    return [path for path in safe_candidates if path and not _url_path_fragment(path)][:limit]


def infer_useful_evidence(context_files: list[str], target_files: list[str]) -> list[str]:
    """Infer compact evidence labels from context and target file overlap."""
    if target_files:
        target_set = set(target_files)
        overlap = [path for path in context_files if path in target_set]
        return dedupe_preserve_order(overlap + target_files)[:MAX_TARGET_FILES]
    return context_files[: min(4, len(context_files))]


def dedupe_preserve_order(items: Iterable[str]) -> list[str]:
    """Deduplicate strings while preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            out.append(item)
            seen.add(item)
    return out


def clean_path(path: str) -> str:
    stripped = path.strip().strip("`'\"()[]{}<>.,:;")
    while stripped.startswith("./"):
        stripped = stripped[2:]
    return stripped


def _url_path_fragment(path: str) -> bool:
    lower = path.lower()
    return (
        lower.startswith("//")
        or "://" in lower
        or lower.startswith("www.")
        or ".com/" in lower
        or ".org/" in lower
        or ".net/" in lower
    )


__all__ = [
    "MAX_FILE_PATHS",
    "MAX_TARGET_FILES",
    "classify_next_action",
    "classify_shell_action",
    "dedupe_preserve_order",
    "extract_file_paths",
    "extract_tool_names",
    "infer_useful_evidence",
    "normalize_tool_name",
    "parse_prompt_data",
]
