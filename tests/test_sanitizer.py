from __future__ import annotations

from photon_action_memory.memory.sanitizer import (
    REDACTED_EMAIL,
    REDACTED_SECRET,
    filter_safe_path_candidates,
    sanitize_path_candidate,
    sanitize_text,
    sanitize_text_with_report,
)


def test_sanitize_text_redacts_secret_assignments() -> None:
    text = "\n".join(
        [
            "api_key=sk-testsecretvalue123456",
            "API key = abcdefghijklmnop",
            "token: abcdefghijklmnop",
            "password='correcthorsebattery'",
            "Authorization: Bearer abcdefghijklmnop1234",
        ]
    )

    sanitized = sanitize_text(text)

    assert sanitized.count(REDACTED_SECRET) == 5
    assert "sk-testsecretvalue123456" not in sanitized
    assert "abcdefghijklmnop" not in sanitized
    assert "correcthorsebattery" not in sanitized


def test_sanitize_text_redacts_secret_like_long_tokens_but_keeps_hashes() -> None:
    hex_digest = "0123456789abcdef0123456789abcdef"
    text = f"openai sk-abcdefghijklmnopqrstuvwxyz123456 hash {hex_digest}"

    sanitized = sanitize_text(text)

    assert f"openai {REDACTED_SECRET}" in sanitized
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in sanitized
    assert hex_digest in sanitized


def test_sanitize_text_replaces_email_addresses() -> None:
    sanitized = sanitize_text("contact user.name+test@example.com for details")

    assert sanitized == f"contact {REDACTED_EMAIL} for details"


def test_sanitize_text_normalizes_sensitive_absolute_paths() -> None:
    text = (
        "repo /Users/alice/project/src/app.py "
        "home /home/bob/.config/tool.toml "
        "tmp /tmp/session/output.log "
        "private /private/tmp/work/cache.json "
        "var /var/folders/session/build.log "
        "opt /opt/local/bin/tool.sh"
    )

    sanitized = sanitize_text(text, workspace_roots=["/Users/alice/project"])

    assert "src/app.py" in sanitized
    assert "[ABS_PATH]/tool.toml" in sanitized
    assert "[ABS_PATH]/output.log" in sanitized
    assert "/Users/alice" not in sanitized
    assert "/home/bob" not in sanitized
    assert "/tmp/session" not in sanitized
    assert "/private/tmp/work" not in sanitized
    assert "/var/folders/session" not in sanitized
    assert "/opt/local/bin" not in sanitized


def test_sanitize_text_removes_ansi_and_control_characters() -> None:
    sanitized = sanitize_text("ok\x1b[31m red\x1b[0m bad\x00char\x08 done\nkeep\ttab")

    assert "\x1b" not in sanitized
    assert "\x00" not in sanitized
    assert "\x08" not in sanitized
    assert sanitized == "ok red bad char  done\nkeep\ttab"


def test_sanitize_text_with_report_counts_redactions() -> None:
    result = sanitize_text_with_report(
        "token=abcdefghijklmnop email a@example.com path /tmp/secret.txt",
        max_chars=20,
    )

    assert result.text.endswith("...[truncated]")
    assert result.report.as_dict() == {
        "secret_assignment": 1,
        "email": 1,
        "url_token": 0,
        "absolute_path": 1,
        "truncated_text": 1,
    }


def test_filter_safe_path_candidates_excludes_secret_bearing_paths() -> None:
    candidates = [
        "src/app.py",
        "src/app.py",
        "logs/sk-abcdefghijklmnopqrstuvwxyz123456.txt",
        "/tmp/build/output.log",
        "https://example.test/file.py?token=abcdefghijklmnop",
    ]

    assert filter_safe_path_candidates(candidates) == ["src/app.py", "[ABS_PATH]/output.log"]


def test_sanitize_path_candidate_normalizes_workspace_paths() -> None:
    assert (
        sanitize_path_candidate(
            "/Users/alice/project/photon_action_memory/memory/sanitizer.py",
            workspace_roots=["/Users/alice/project"],
        )
        == "photon_action_memory/memory/sanitizer.py"
    )
    assert sanitize_path_candidate("notes/token=abcdefghijklmnop.txt") is None
