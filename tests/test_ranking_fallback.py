from __future__ import annotations

from photon_action_memory import SCHEMA_VERSION
from photon_action_memory.api.schema import SuggestRequest
from photon_action_memory.api.server import build_fallback_suggestions
from photon_action_memory.ranking.guards import is_destructive_command


def _request(
    *,
    user_request: str = "fix the failing test",
    touched_files: list[str] | None = None,
    recent_events: list[dict[str, object]] | None = None,
    max_suggestions: int = 5,
    max_evidence_chars: int = 4000,
) -> SuggestRequest:
    return SuggestRequest.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "request_id": "req-ranking",
            "agent": {"name": "codex"},
            "repo": {"root": "/repo", "name": "example"},
            "task": {"user_request": user_request, "mode": "act"},
            "working_memory": {"touched_files": touched_files or []},
            "recent_events": recent_events or [],
            "budget": {
                "max_suggestions": max_suggestions,
                "max_evidence_chars": max_evidence_chars,
            },
        }
    )


def test_fallback_ranking_is_deterministic_for_same_input() -> None:
    request = _request(
        touched_files=["src/app.py", "tests/test_app.py"],
        recent_events=[
            {
                "type": "tool_result",
                "status": "error",
                "summary": "pytest failed in tests/test_app.py:12",
            },
            {
                "type": "tool_result",
                "tool": "rg",
                "summary": "searched for app setup",
                "query": "setup",
            },
        ],
    )

    first = build_fallback_suggestions(request)
    second = build_fallback_suggestions(request)

    assert first.model_dump() == second.model_dump()


def test_recent_error_file_path_is_prioritized_for_inspection() -> None:
    response = build_fallback_suggestions(
        _request(
            touched_files=["src/ordinary.py"],
            recent_events=[
                {
                    "type": "tool_result",
                    "status": "failed",
                    "summary": "Traceback in photon_action_memory/ranking/fallback.py:44",
                }
            ],
        )
    )

    assert response.suggestions[0].kind == "inspect"
    assert response.suggestions[0].target == "photon_action_memory/ranking/fallback.py"


def test_fallback_respects_top_k_and_evidence_char_budget() -> None:
    response = build_fallback_suggestions(
        _request(
            touched_files=["a.py", "b.py", "c.py"],
            recent_events=[
                {
                    "type": "tool_result",
                    "summary": "a.py " + ("x" * 20),
                },
                {
                    "type": "tool_result",
                    "summary": "b.py " + ("y" * 20),
                },
            ],
            max_suggestions=1,
            max_evidence_chars=12,
        )
    )

    assert len(response.suggestions) == 1
    assert sum(len(item.summary) for item in response.evidence) <= 12


def test_repeated_read_and_search_actions_emit_warning() -> None:
    response = build_fallback_suggestions(
        _request(
            recent_events=[
                {
                    "type": "tool_call",
                    "tool": "read",
                    "summary": "read src/app.py",
                    "target": "src/app.py",
                },
                {
                    "type": "tool_call",
                    "tool": "read",
                    "summary": "read src/app.py",
                    "target": "src/app.py",
                },
                {
                    "type": "tool_call",
                    "tool": "rg",
                    "summary": "search setup",
                    "query": "setup",
                },
                {
                    "type": "tool_call",
                    "tool": "rg",
                    "summary": "search setup",
                    "query": "setup",
                },
            ],
        )
    )

    warning_kinds = [warning.kind for warning in response.warnings]
    assert warning_kinds.count("repeat_failure") == 2


def test_edit_like_request_without_evidence_emits_missing_evidence_warning() -> None:
    response = build_fallback_suggestions(
        _request(user_request="edit src/app.py", recent_events=[])
    )

    assert "missing_evidence" in [warning.kind for warning in response.warnings]


def test_destructive_shell_command_is_not_suggested() -> None:
    response = build_fallback_suggestions(
        _request(
            user_request="fix build",
            recent_events=[
                {
                    "type": "tool_result",
                    "status": "failed",
                    "summary": "build failed after a shell command",
                    "command": "rm -rf /tmp/project",
                }
            ],
        )
    )

    assert is_destructive_command("rm -rf /tmp/project")
    assert all(suggestion.command != "rm -rf /tmp/project" for suggestion in response.suggestions)
