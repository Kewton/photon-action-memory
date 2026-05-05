"""Tests for the raw tool-log default-deny policy (issue #37).

Acceptance criteria verified:
- raw tool stdout/stderr are not included in ContextPack items
- full grep output / build log / file content are denied by default
- secret-like strings / absolute home paths / token-like values are not prompt-visible
- denied items appear in omitted with reasons
- raw_tool_tokens_in_prompt is approximately zero
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionSummary,
    ContextPackBudget,
    Fact,
    Validity,
)
from photon_action_memory.api.server import create_app
from photon_action_memory.context.pack import build_context_pack
from photon_action_memory.context.raw_policy import (
    RAW_DENIED_KINDS,
    RawEvidenceItem,
    evaluate_raw_item,
    has_sensitive_content,
)
from photon_action_memory.context.render import estimate_tokens
from photon_action_memory.memory.store import SQLiteEventStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raw(item_id: str, kind: str, content: str = "some output") -> RawEvidenceItem:
    return RawEvidenceItem(item_id=item_id, kind=kind, content=content)


def _pack_with_raw(
    raw_items: list[RawEvidenceItem],
    max_tokens: int = 800,
) -> tuple:  # type: ignore[type-arg]
    return build_context_pack(
        request_id="req-raw-test",
        session_id=None,
        repo_id=None,
        summaries=[],
        budget=ContextPackBudget(max_memory_tokens=max_tokens),
        raw_items=raw_items,
    )


# ---------------------------------------------------------------------------
# evaluate_raw_item - kind-based denial
# ---------------------------------------------------------------------------


def test_stdout_is_denied() -> None:
    item = _raw("r-1", "stdout", "$ cargo build\nCompiling photon v0.1.0\n")
    decision, reason = evaluate_raw_item(item)
    assert decision == "deny"
    assert "stdout" in reason


def test_stderr_is_denied() -> None:
    item = _raw("r-2", "stderr", "error[E0308]: mismatched types\n")
    decision, reason = evaluate_raw_item(item)
    assert decision == "deny"
    assert "stderr" in reason


def test_grep_output_is_denied() -> None:
    item = _raw("r-3", "grep_output", "src/main.rs:10: fn main() {")
    decision, reason = evaluate_raw_item(item)
    assert decision == "deny"
    assert "grep_output" in reason


def test_build_log_is_denied() -> None:
    item = _raw("r-4", "build_log", "BUILD SUCCESSFUL in 3s")
    decision, reason = evaluate_raw_item(item)
    assert decision == "deny"
    assert "build_log" in reason


def test_file_content_is_denied() -> None:
    item = _raw("r-5", "file_content", 'fn main() { println!("hello"); }')
    decision, reason = evaluate_raw_item(item)
    assert decision == "deny"
    assert "file_content" in reason


def test_all_raw_denied_kinds_are_denied() -> None:
    for kind in RAW_DENIED_KINDS:
        item = _raw(f"r-{kind}", kind, "some content")
        decision, reason = evaluate_raw_item(item)
        assert decision == "deny", f"expected deny for kind={kind}"
        assert reason, f"expected non-empty reason for kind={kind}"


def test_unknown_raw_kind_is_still_denied_by_default() -> None:
    item = _raw("r-unknown", "custom_raw_kind", "some raw output")
    decision, reason = evaluate_raw_item(item)
    assert decision == "deny"
    assert "default" in reason


# ---------------------------------------------------------------------------
# has_sensitive_content - secret / path / token detection
# ---------------------------------------------------------------------------


def test_secret_kv_pair_detected() -> None:
    assert has_sensitive_content("api_key=sk-abc123secret456789")
    assert has_sensitive_content("password: hunter2")
    assert has_sensitive_content("API_KEY=abcdefghijklmnop")


def test_bearer_token_detected() -> None:
    assert has_sensitive_content("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xxx")


def test_openai_style_token_detected() -> None:
    assert has_sensitive_content("using key sk-abcdefghijklmnopqrstuvwxyz1234567890")


def test_github_pat_detected() -> None:
    assert has_sensitive_content("export GITHUB_TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabc")


def test_absolute_home_path_detected() -> None:
    assert has_sensitive_content("/home/alice/.ssh/id_rsa")
    assert has_sensitive_content("/Users/bob/Documents/secret.txt")
    assert has_sensitive_content("/root/.bashrc")


def test_safe_content_not_flagged() -> None:
    assert not has_sensitive_content("FACT: server lives in api/server.py")
    assert not has_sensitive_content("build succeeded in 3s")
    assert not has_sensitive_content("relative/path/to/file.py")


# ---------------------------------------------------------------------------
# evaluate_raw_item - sensitive content denial
# ---------------------------------------------------------------------------


def test_sensitive_content_in_unknown_kind_is_denied() -> None:
    item = _raw("r-s1", "custom_output", "password=hunter2")
    decision, reason = evaluate_raw_item(item)
    assert decision == "deny"
    assert "sensitive" in reason


def test_home_path_in_unknown_kind_is_denied() -> None:
    item = _raw("r-s2", "note", "/home/alice/workspace/project/main.py")
    decision, reason = evaluate_raw_item(item)
    assert decision == "deny"
    assert "sensitive" in reason


# ---------------------------------------------------------------------------
# build_context_pack - raw items stay out of items[*].text
# ---------------------------------------------------------------------------


def test_raw_items_not_in_pack_items() -> None:
    raw = [_raw("r-1", "stdout", "lots of build output")]
    pack, _ = _pack_with_raw(raw)
    assert pack.items == []


def test_raw_items_appear_in_omitted() -> None:
    raw = [
        _raw("r-1", "stdout", "build output line 1"),
        _raw("r-2", "stderr", "error: missing semicolon"),
    ]
    pack, _ = _pack_with_raw(raw)
    assert len(pack.omitted) == 2
    omitted_ids = {o.id for o in pack.omitted}
    assert "r-1" in omitted_ids
    assert "r-2" in omitted_ids


def test_raw_items_omitted_with_reasons() -> None:
    raw = [_raw("r-1", "grep_output", "src/main.rs:5: use std::io")]
    pack, _ = _pack_with_raw(raw)
    assert len(pack.omitted) == 1
    assert pack.omitted[0].reason
    assert "deny" in pack.omitted[0].reason or "raw" in pack.omitted[0].reason.lower()


def test_raw_items_produce_deny_decisions() -> None:
    raw = [_raw("r-1", "build_log", "BUILD SUCCESSFUL")]
    _, decisions = _pack_with_raw(raw)
    assert len(decisions) == 1
    dec = decisions[0]
    assert dec.decision == "deny"
    assert dec.item_kind == "raw_tool_log"
    assert dec.reason is not None


def test_raw_decision_has_policy_field() -> None:
    raw = [_raw("r-1", "stdout", "output")]
    _, decisions = _pack_with_raw(raw)
    dec = decisions[0]
    assert dec.policy is not None
    assert dec.policy.raw_evidence_policy == "raw_tool_log_default_deny"


def test_secret_in_raw_item_does_not_reach_items() -> None:
    raw = [_raw("r-secret", "custom_output", "API_KEY=mysecretapikey123456")]
    pack, decisions = _pack_with_raw(raw)
    assert pack.items == []
    assert len(pack.omitted) == 1
    assert decisions[0].decision == "deny"


def test_home_path_in_raw_item_does_not_reach_items() -> None:
    raw = [_raw("r-path", "note", "config at /home/alice/.config/app.toml")]
    pack, _ = _pack_with_raw(raw)
    assert pack.items == []
    assert len(pack.omitted) == 1


# ---------------------------------------------------------------------------
# raw_tool_tokens_in_prompt is approximately 0
#
# Verify that even if raw items contain many tokens, none end up in the
# prompt-visible items list.
# ---------------------------------------------------------------------------


def _raw_tool_tokens_in_prompt(pack_items: list) -> int:  # type: ignore[type-arg]
    """Sum estimated tokens for any item whose text contains raw tool output markers."""
    total = 0
    for item in pack_items:
        total += estimate_tokens(item.text)
    return total


def test_raw_tool_tokens_in_prompt_is_zero_with_only_raw_items() -> None:
    large_raw = [
        _raw(f"r-{i}", kind, "x" * 2000)
        for i, kind in enumerate(["stdout", "stderr", "grep_output", "build_log", "file_content"])
    ]
    pack, _ = _pack_with_raw(large_raw)
    assert _raw_tool_tokens_in_prompt(pack.items) == 0


def _fact(text: str, evidence_id: str = "ev-1") -> Fact:
    return Fact(text=text, evidence_ids=[evidence_id], confidence=0.9)


def _make_summary_simple(summary_id: str, facts: list[Fact]) -> ActionSummary:
    return ActionSummary(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        summary_id=summary_id,
        session_id="sess-1",
        facts=facts,
        hypotheses=[],
        failed_attempts=[],
        avoid=[],
        validity=Validity(status="valid"),
        token_cost=None,
    )


def test_raw_tool_tokens_in_prompt_zero_mixed_with_summaries() -> None:
    """Raw items must not add tokens to items even when summaries are also present."""
    summaries: list[ActionSummary] = [
        _make_summary_simple("sum-1", facts=[_fact("server is in api/")])
    ]
    raw = [_raw("r-1", "stdout", "build output " * 100)]
    pack, decisions = build_context_pack(
        request_id="req-mixed",
        session_id=None,
        repo_id=None,
        summaries=summaries,
        budget=ContextPackBudget(max_memory_tokens=800),
        raw_items=raw,
    )
    # Summary items are admitted, raw items are denied
    assert len(pack.items) == 1
    assert "stdout" not in pack.items[0].text
    assert "build output" not in pack.items[0].text
    # Omitted list contains the raw item
    assert any(o.id == "r-1" for o in pack.omitted)
    # Raw tokens don't add to prompt
    raw_tokens_in_prompt = sum(
        estimate_tokens(item.text)
        for item in pack.items
        if any(word in item.text for word in ["build output", "stdout"])
    )
    assert raw_tokens_in_prompt == 0


# ---------------------------------------------------------------------------
# API integration - raw_evidence in ContextPackRequest extras is denied
# ---------------------------------------------------------------------------


def _pack_api_request(
    *,
    raw_evidence: list[dict] | None = None,  # type: ignore[type-arg]
    max_tokens: int = 800,
) -> dict:  # type: ignore[type-arg]
    req: dict = {  # type: ignore[type-arg]
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": "req-raw-api",
        "agent": {"name": "codex"},
        "repo": {"root": "/tmp", "name": "photon-test"},
        "task": {
            "user_request": "fix bug",
            "mode": "act",
            "summary": "fixing a bug",
        },
        "working_memory": {"touched_files": []},
        "recent_event_ids": [],
        "candidate_summary_ids": [],
        "budget": {"max_memory_tokens": max_tokens, "max_evidence_chars": 1200},
    }
    if raw_evidence is not None:
        req["raw_evidence"] = raw_evidence
    return req


def test_api_raw_evidence_extras_are_denied(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    raw_evidence = [
        {"item_id": "raw-stdout-1", "kind": "stdout", "content": "cargo build output..."},
        {"item_id": "raw-stderr-1", "kind": "stderr", "content": "warning: unused var"},
    ]
    with TestClient(app) as client:
        response = client.post(
            "/v1/context/pack", json=_pack_api_request(raw_evidence=raw_evidence)
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["context_pack"]["items"] == []
    omitted_ids = {o["id"] for o in payload["context_pack"]["omitted"]}
    assert "raw-stdout-1" in omitted_ids
    assert "raw-stderr-1" in omitted_ids


def test_api_raw_evidence_deny_decisions_have_policy(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    raw_evidence = [{"item_id": "raw-1", "kind": "build_log", "content": "BUILD SUCCESSFUL"}]
    with TestClient(app) as client:
        response = client.post(
            "/v1/context/pack", json=_pack_api_request(raw_evidence=raw_evidence)
        )

    payload = response.json()
    decisions = payload["admission_decisions"]
    assert len(decisions) == 1
    dec = decisions[0]
    assert dec["decision"] == "deny"
    assert dec["item_kind"] == "raw_tool_log"
    assert dec["policy"]["raw_evidence_policy"] == "raw_tool_log_default_deny"


def test_api_no_raw_evidence_field_is_fine(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    with TestClient(app) as client:
        response = client.post("/v1/context/pack", json=_pack_api_request())

    assert response.status_code == 200
    assert response.json()["sidecar_status"] == "ok"


def test_api_secret_in_raw_evidence_is_denied(tmp_path: Path) -> None:
    app = create_app(SQLiteEventStore(tmp_path / "events.sqlite"))
    raw_evidence = [
        {
            "item_id": "raw-secret",
            "kind": "custom_output",
            "content": "API_KEY=supersecretvalue123456789",
        }
    ]
    with TestClient(app) as client:
        response = client.post(
            "/v1/context/pack", json=_pack_api_request(raw_evidence=raw_evidence)
        )

    payload = response.json()
    assert payload["context_pack"]["items"] == []
    assert len(payload["context_pack"]["omitted"]) == 1
    for item_text in [i["text"] for i in payload["context_pack"]["items"]]:
        assert "supersecretvalue" not in item_text
