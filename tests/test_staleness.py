"""Tests for StalenessGuard, FileFingerprinter, and ContextPack integration."""

from __future__ import annotations

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionSummary,
    ContextPackBudget,
    Fact,
    Hypothesis,
)
from photon_action_memory.context.pack import build_context_pack
from photon_action_memory.memory.staleness import (
    FileFingerprinter,
    StalenessContext,
    StalenessGuard,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _summary(
    summary_id: str = "sum-test",
    *,
    commit: str | None = None,
    task_signature: str | None = None,
    facts: list[Fact] | None = None,
    hypotheses: list[Hypothesis] | None = None,
) -> ActionSummary:
    return ActionSummary(
        schema_version=DEFAULT_SCHEMA_VERSION_V2,
        summary_id=summary_id,
        session_id="sess-1",
        commit=commit,
        task_signature=task_signature,
        facts=facts if facts is not None else [Fact(text="some fact", evidence_ids=["ev-1"])],
        hypotheses=hypotheses or [],
    )


def _fact(text: str) -> Fact:
    return Fact(text=text, evidence_ids=["ev-1"])


# ---------------------------------------------------------------------------
# FileFingerprinter
# ---------------------------------------------------------------------------


def test_fingerprint_content_is_deterministic() -> None:
    fp1 = FileFingerprinter.fingerprint_content("hello world")
    fp2 = FileFingerprinter.fingerprint_content("hello world")
    assert fp1 == fp2


def test_fingerprint_content_differs_for_different_content() -> None:
    assert FileFingerprinter.fingerprint_content("v1") != FileFingerprinter.fingerprint_content(
        "v2"
    )


def test_fingerprint_content_is_16_hex_chars() -> None:
    fp = FileFingerprinter.fingerprint_content("anything")
    assert len(fp) == 16
    assert all(c in "0123456789abcdef" for c in fp)


def test_fingerprint_line_range_is_deterministic() -> None:
    content = "line1\nline2\nline3\nline4"
    assert FileFingerprinter.fingerprint_line_range(
        content, 2, 3
    ) == FileFingerprinter.fingerprint_line_range(content, 2, 3)


def test_fingerprint_line_range_differs_for_modified_lines() -> None:
    original = "line1\nline2\nline3"
    modified = "line1\nMODIFIED\nline3"
    fp1 = FileFingerprinter.fingerprint_line_range(original, 2, 2)
    fp2 = FileFingerprinter.fingerprint_line_range(modified, 2, 2)
    assert fp1 != fp2


def test_fingerprint_line_range_key_format() -> None:
    assert FileFingerprinter.line_range_key("src/main.py", 10, 20) == "src/main.py:10:20"


# ---------------------------------------------------------------------------
# StalenessGuard - commit hash
# ---------------------------------------------------------------------------


def test_commit_hash_change_returns_stale() -> None:
    guard = StalenessGuard()
    summary = _summary(commit="aaaa1111bbbb2222")
    context = StalenessContext(current_commit="cccc3333dddd4444")
    result = guard.check(summary, context)
    assert result.status == "stale"
    assert result.reason is not None
    assert "commit" in result.reason


def test_commit_unchanged_not_stale() -> None:
    guard = StalenessGuard()
    summary = _summary(commit="aaaa1111")
    context = StalenessContext(current_commit="aaaa1111")
    result = guard.check(summary, context)
    assert result.status == "valid"


def test_commit_check_skipped_when_summary_has_no_commit() -> None:
    guard = StalenessGuard()
    summary = _summary(commit=None)
    context = StalenessContext(current_commit="some-commit")
    result = guard.check(summary, context)
    assert result.status == "valid"


# ---------------------------------------------------------------------------
# StalenessGuard - branch
# ---------------------------------------------------------------------------


def test_branch_change_returns_stale() -> None:
    guard = StalenessGuard()
    summary = _summary()
    context = StalenessContext(current_branch="main")
    result = guard.check(summary, context, summary_branch="feature/my-branch")
    assert result.status == "stale"
    assert result.reason is not None
    assert "branch" in result.reason


def test_branch_unchanged_not_stale() -> None:
    guard = StalenessGuard()
    summary = _summary()
    context = StalenessContext(current_branch="main")
    result = guard.check(summary, context, summary_branch="main")
    assert result.status == "valid"


def test_branch_check_skipped_when_summary_branch_not_provided() -> None:
    guard = StalenessGuard()
    summary = _summary()
    context = StalenessContext(current_branch="main")
    result = guard.check(summary, context, summary_branch=None)
    assert result.status == "valid"


# ---------------------------------------------------------------------------
# StalenessGuard - task signature
# ---------------------------------------------------------------------------


def test_task_signature_change_returns_stale() -> None:
    guard = StalenessGuard()
    summary = _summary(task_signature="implement-feature-x")
    context = StalenessContext(current_task_signature="debug-issue-y")
    result = guard.check(summary, context)
    assert result.status == "stale"
    assert result.reason is not None
    assert "task" in result.reason


def test_task_signature_unchanged_not_stale() -> None:
    guard = StalenessGuard()
    summary = _summary(task_signature="implement-feature-x")
    context = StalenessContext(current_task_signature="implement-feature-x")
    result = guard.check(summary, context)
    assert result.status == "valid"


# ---------------------------------------------------------------------------
# StalenessGuard - file fingerprint
# ---------------------------------------------------------------------------


def test_file_fingerprint_change_returns_stale() -> None:
    guard = StalenessGuard()
    summary = _summary()
    old_fp = FileFingerprinter.fingerprint_content("original content")
    new_fp = FileFingerprinter.fingerprint_content("modified content")
    context = StalenessContext(current_file_fingerprints={"src/main.py": new_fp})
    result = guard.check(summary, context, summary_file_fingerprints={"src/main.py": old_fp})
    assert result.status == "stale"
    assert result.reason is not None
    assert "src/main.py" in result.reason


def test_file_fingerprint_unchanged_not_stale() -> None:
    guard = StalenessGuard()
    summary = _summary()
    fp = FileFingerprinter.fingerprint_content("stable content")
    context = StalenessContext(current_file_fingerprints={"src/main.py": fp})
    result = guard.check(summary, context, summary_file_fingerprints={"src/main.py": fp})
    assert result.status == "valid"


def test_missing_file_reference_returns_unknown() -> None:
    guard = StalenessGuard()
    summary = _summary()
    fp = FileFingerprinter.fingerprint_content("some content")
    context = StalenessContext(current_file_fingerprints={})  # file not found
    result = guard.check(summary, context, summary_file_fingerprints={"src/missing.py": fp})
    assert result.status == "unknown"
    assert result.reason is not None
    assert "src/missing.py" in result.reason


def test_file_check_skipped_when_current_fingerprints_none() -> None:
    """No current fingerprints provided (None) -> skip check, fail-open."""
    guard = StalenessGuard()
    summary = _summary()
    fp = FileFingerprinter.fingerprint_content("some content")
    context = StalenessContext()  # current_file_fingerprints=None by default
    result = guard.check(summary, context, summary_file_fingerprints={"src/main.py": fp})
    assert result.status == "valid"


# ---------------------------------------------------------------------------
# StalenessGuard - line range fingerprint
# ---------------------------------------------------------------------------


def test_line_range_fingerprint_change_returns_partial() -> None:
    guard = StalenessGuard()
    summary = _summary()
    old_fp = FileFingerprinter.fingerprint_line_range("line1\nline2\nline3", 2, 2)
    new_fp = FileFingerprinter.fingerprint_line_range("line1\nCHANGED\nline3", 2, 2)
    key = FileFingerprinter.line_range_key("src/main.py", 2, 2)
    context = StalenessContext(current_line_fingerprints={key: new_fp})
    result = guard.check(summary, context, summary_line_fingerprints={key: old_fp})
    assert result.status == "partial"
    assert result.reason is not None
    assert "src/main.py" in result.reason


def test_missing_line_range_reference_returns_unknown() -> None:
    guard = StalenessGuard()
    summary = _summary()
    fp = FileFingerprinter.fingerprint_line_range("line1\nline2", 1, 2)
    key = FileFingerprinter.line_range_key("src/main.py", 1, 2)
    context = StalenessContext(current_line_fingerprints={})  # key not found
    result = guard.check(summary, context, summary_line_fingerprints={key: fp})
    assert result.status == "unknown"
    assert result.reason is not None


# ---------------------------------------------------------------------------
# StalenessGuard - contradiction
# ---------------------------------------------------------------------------


def test_later_event_contradiction_returns_contradicted() -> None:
    fact_text = "the database uses PostgreSQL"
    guard = StalenessGuard()
    summary = _summary(facts=[_fact(fact_text)])
    context = StalenessContext(refuted_claims=[fact_text])
    result = guard.check(summary, context)
    assert result.status == "contradicted"
    assert result.reason is not None


def test_contradiction_checks_hypotheses_too() -> None:
    hypo_text = "the bottleneck may be in the parser"
    guard = StalenessGuard()
    summary = _summary(
        facts=[],
        hypotheses=[Hypothesis(text=hypo_text, evidence_ids=[], confidence=0.5, status="open")],
    )
    context = StalenessContext(refuted_claims=[hypo_text])
    result = guard.check(summary, context)
    assert result.status == "contradicted"


def test_unrelated_refuted_claim_not_triggered() -> None:
    guard = StalenessGuard()
    summary = _summary(facts=[_fact("the database uses PostgreSQL")])
    context = StalenessContext(refuted_claims=["the server uses nginx"])
    result = guard.check(summary, context)
    assert result.status == "valid"


# ---------------------------------------------------------------------------
# StalenessGuard - valid case
# ---------------------------------------------------------------------------


def test_valid_case_remains_valid() -> None:
    guard = StalenessGuard()
    summary = _summary(commit="abc", task_signature="task-1")
    context = StalenessContext(
        current_commit="abc",
        current_branch="main",
        current_task_signature="task-1",
    )
    result = guard.check(summary, context, summary_branch="main")
    assert result.status == "valid"
    assert result.reason is None


def test_all_checks_skipped_with_empty_context() -> None:
    guard = StalenessGuard()
    summary = _summary()
    context = StalenessContext()
    result = guard.check(summary, context)
    assert result.status == "valid"


# ---------------------------------------------------------------------------
# StalenessGuard.apply()
# ---------------------------------------------------------------------------


def test_apply_updates_summary_validity_to_stale() -> None:
    guard = StalenessGuard()
    summary = _summary(commit="old-commit-aaa")
    context = StalenessContext(current_commit="new-commit-bbb")
    updated = guard.apply(summary, context)
    assert updated.validity.status == "stale"
    assert updated.validity.reason is not None
    assert "commit" in updated.validity.reason


def test_apply_does_not_mutate_original_summary() -> None:
    guard = StalenessGuard()
    summary = _summary(commit="old-commit-aaa")
    context = StalenessContext(current_commit="new-commit-bbb")
    _ = guard.apply(summary, context)
    assert summary.validity.status == "valid"  # original unchanged


def test_apply_sets_valid_when_no_staleness_detected() -> None:
    guard = StalenessGuard()
    summary = _summary(commit="same-commit")
    context = StalenessContext(current_commit="same-commit")
    updated = guard.apply(summary, context)
    assert updated.validity.status == "valid"
    assert updated.validity.reason is None


# ---------------------------------------------------------------------------
# Integration: stale summaries omitted from ContextPack by default
# ---------------------------------------------------------------------------


def test_stale_summary_omitted_from_context_pack_via_guard() -> None:
    """End-to-end: guard detects staleness, apply() sets validity, pack omits it."""
    guard = StalenessGuard()
    summary = _summary("sum-stale", commit="old-abc123", facts=[_fact("old fact")])
    context = StalenessContext(current_commit="new-xyz789")
    stale_summary = guard.apply(summary, context)

    assert stale_summary.validity.status == "stale"

    pack, decisions = build_context_pack(
        request_id="req-staleness",
        session_id="sess-1",
        repo_id="test-repo",
        summaries=[stale_summary],
        budget=ContextPackBudget(),
    )
    assert len(pack.items) == 0
    assert len(pack.omitted) == 1
    assert pack.omitted[0].id == "sum-stale"


def test_fresh_summary_admitted_alongside_stale_omitted() -> None:
    guard = StalenessGuard()
    stale = guard.apply(
        _summary("sum-stale", commit="old-111", facts=[_fact("old info")]),
        StalenessContext(current_commit="new-222"),
    )
    fresh = _summary("sum-fresh", commit="new-222", facts=[_fact("fresh info")])

    pack, decisions = build_context_pack(
        request_id="req-mixed",
        session_id=None,
        repo_id=None,
        summaries=[stale, fresh],
        budget=ContextPackBudget(),
    )
    assert len(pack.items) == 1
    assert pack.items[0].id == "sum-fresh"
    assert len(pack.omitted) == 1
    assert pack.omitted[0].id == "sum-stale"


# ---------------------------------------------------------------------------
# Integration: stale reason appears in admission decision and omitted reason
# ---------------------------------------------------------------------------


def test_stale_reason_in_omitted_item() -> None:
    """validity.reason from the guard appears in the pack's omitted item reason."""
    guard = StalenessGuard()
    summary = _summary("sum-reason", commit="old-commit-hash", facts=[_fact("some fact")])
    context = StalenessContext(current_commit="new-commit-hash")
    stale_summary = guard.apply(summary, context)

    assert stale_summary.validity.reason is not None

    pack, _ = build_context_pack(
        request_id="req-reason",
        session_id=None,
        repo_id=None,
        summaries=[stale_summary],
        budget=ContextPackBudget(),
    )
    omitted = pack.omitted[0]
    assert "stale" in omitted.reason
    assert stale_summary.validity.reason in omitted.reason


def test_stale_reason_in_admission_decision() -> None:
    """validity.reason from the guard appears in the ContextAdmissionDecision reason."""
    guard = StalenessGuard()
    summary = _summary("sum-dec", commit="old-commit-hash", facts=[_fact("a fact")])
    context = StalenessContext(current_commit="new-commit-hash")
    stale_summary = guard.apply(summary, context)

    _, decisions = build_context_pack(
        request_id="req-dec",
        session_id=None,
        repo_id=None,
        summaries=[stale_summary],
        budget=ContextPackBudget(),
    )
    assert len(decisions) == 1
    dec = decisions[0]
    assert dec.decision == "omit"
    assert dec.reason is not None
    assert "stale" in dec.reason
    assert stale_summary.validity.reason is not None
    assert stale_summary.validity.reason in dec.reason


def test_contradicted_reason_in_omitted_item() -> None:
    guard = StalenessGuard()
    fact_text = "cache invalidation uses Redis"
    summary = _summary("sum-contra", facts=[_fact(fact_text)])
    context = StalenessContext(refuted_claims=[fact_text])
    contradicted = guard.apply(summary, context)

    assert contradicted.validity.status == "contradicted"

    pack, _ = build_context_pack(
        request_id="req-contra",
        session_id=None,
        repo_id=None,
        summaries=[contradicted],
        budget=ContextPackBudget(),
    )
    assert len(pack.omitted) == 1
    assert "contradicted" in pack.omitted[0].reason


# ---------------------------------------------------------------------------
# Prompt-safety: reasons must not leak raw file contents or full commit hashes
# ---------------------------------------------------------------------------


def test_reason_does_not_contain_raw_file_contents() -> None:
    guard = StalenessGuard()
    summary = _summary()
    secret_content = "SECRET_API_KEY=super_secret_value_abcdef12345"
    old_fp = FileFingerprinter.fingerprint_content("old content")
    new_fp = FileFingerprinter.fingerprint_content(secret_content)
    context = StalenessContext(current_file_fingerprints={"src/config.py": new_fp})
    result = guard.check(summary, context, summary_file_fingerprints={"src/config.py": old_fp})
    assert result.status == "stale"
    assert result.reason is not None
    assert secret_content not in result.reason
    assert "old content" not in result.reason


def test_reason_truncates_full_length_commit_hashes() -> None:
    guard = StalenessGuard()
    full_old = "a" * 40
    full_new = "b" * 40
    summary = _summary(commit=full_old)
    context = StalenessContext(current_commit=full_new)
    result = guard.check(summary, context)
    assert result.status == "stale"
    assert result.reason is not None
    # Full 40-char hashes must not appear verbatim in the reason
    assert full_old not in result.reason
    assert full_new not in result.reason


def test_reason_for_branch_change_is_prompt_safe() -> None:
    guard = StalenessGuard()
    summary = _summary()
    context = StalenessContext(current_branch="main")
    result = guard.check(summary, context, summary_branch="feature/xyz")
    assert result.status == "stale"
    assert result.reason is not None
    assert "branch" in result.reason
    # Branch names are safe identifiers, acceptable to include
    assert "feature/xyz" in result.reason or "main" in result.reason
