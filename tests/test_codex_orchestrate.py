from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "codex_orchestrate.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("codex_orchestrate", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_slugify_keeps_safe_branch_text() -> None:
    module = load_script()

    assert module.slugify("Add Codex Harness!") == "add-codex-harness"
    assert module.slugify("!!!") == "task"


def test_analyze_issue_extracts_acceptance_files_and_tests() -> None:
    module = load_script()
    issue = module.Issue(
        number=12,
        title="Add dry-run planner",
        body=(
            "Implement planner for `scripts/codex_orchestrate.py`.\n\n"
            "## Acceptance Criteria\n"
            "- `pytest -q` passes\n"
            "- writes `workspace/management/runs/example/manifest.md`\n"
        ),
        labels=("feature",),
    )

    analysis = module.analyze_issue(issue, "photon-action-memory", skip_enhance=False)

    assert analysis.enhancement_needed is False
    assert analysis.branch_name == "feature/issue-12-add-dry-run-planner"
    assert "scripts/codex_orchestrate.py" in analysis.suspected_files
    assert "pytest" in analysis.test_expectations
    assert analysis.acceptance_criteria


def test_analyze_issue_skips_markdown_heading_for_objective() -> None:
    module = load_script()
    issue = module.Issue(
        number=2,
        title="[P0][M1] Define v1 sidecar schema",
        body=(
            "## 概要\n"
            "`workspace/v0.1.0/05_development_preparation_plan.md` の M1 Schema First に従い、"
            "v1 sidecar schema を実装する。\n\n"
            "## 完了条件\n"
            "- `schema_version` が request / response / event に必須である\n"
        ),
    )

    analysis = module.analyze_issue(issue, "photon-action-memory", skip_enhance=False)

    assert analysis.objective.startswith("`workspace/v0.1.0/05_development_preparation_plan.md`")
    assert analysis.objective != "概要"


def test_extract_file_candidates_ignores_absolute_path_fragments() -> None:
    module = load_script()
    candidates = module.extract_file_candidates(
        "参照: `/Users/me/repo/external/scripts/export_agent_training_data.py`\n"
        "対象: `photon_action_memory/memory/sanitizer.py`\n"
    )

    assert "Users/me/repo/external/scripts/export_agent_training_data.py" not in candidates
    assert "photon_action_memory/memory/sanitizer.py" in candidates


def test_classify_file_candidates_splits_external_references() -> None:
    module = load_script()

    suspected, references = module.classify_file_candidates(
        [
            "photon-mlx-develop/scripts/export_agent_training_data.py",
            "photon_action_memory/memory/sanitizer.py",
        ]
    )

    assert suspected == ["photon_action_memory/memory/sanitizer.py"]
    assert references == ["photon-mlx-develop/scripts/export_agent_training_data.py"]


def test_issue_2_to_5_dependency_batches_are_not_fully_serial() -> None:
    module = load_script()
    issues = [
        module.Issue(2, "[P0][M1] Define v1 sidecar schema", "schema EventRecord"),
        module.Issue(3, "[P0][M3] Implement sanitizer module", "sanitizer redact secret token"),
        module.Issue(
            4, "[P0][M2] Implement local SQLite event store", "SQLite local-first storage"
        ),
        module.Issue(
            5, "[P0][M2] Implement sidecar health/events/suggest", "FastAPI sidecar endpoint client"
        ),
    ]
    analyses = [
        module.analyze_issue(issue, "photon-action-memory", skip_enhance=True) for issue in issues
    ]

    batches, merge_order = module.classify_batches(analyses, "")

    assert batches[0] == [2, 3]
    assert batches[1:] == [[4], [5]]
    assert merge_order == [2, 3, 4, 5]


def test_build_issue_body_with_orchestration_notes_is_idempotent() -> None:
    module = load_script()
    issue = module.Issue(
        number=9,
        title="Clarify issue",
        body="Original body\n\n## 完了条件\n- Works\n",
    )
    analysis = module.analyze_issue(issue, "photon-action-memory", skip_enhance=False)

    first = module.build_issue_body_with_orchestration_notes(analysis)
    second = module.build_issue_body_with_orchestration_notes(
        module.IssueAnalysis(
            issue=module.Issue(issue.number, issue.title, first, issue.labels),
            objective=analysis.objective,
            acceptance_criteria=analysis.acceptance_criteria,
            suspected_files=analysis.suspected_files,
            reference_files=analysis.reference_files,
            test_expectations=analysis.test_expectations,
            enhancement_needed=analysis.enhancement_needed,
            questions=analysis.questions,
            branch_name=analysis.branch_name,
            worktree_path=analysis.worktree_path,
            dependency_hints=analysis.dependency_hints,
        )
    )

    assert first == second
    assert first.count("<!-- codex-orchestrate-notes -->") == 1


def test_write_artifacts_from_fixture(tmp_path: Path) -> None:
    module = load_script()
    fixture = tmp_path / "issues.json"
    fixture.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "number": 1,
                        "title": "Update schema docs",
                        "body": "Touch `workspace/management/codex_harness_spec.md`.\n",
                        "labels": ["docs"],
                    },
                    {
                        "number": 2,
                        "title": "Add script tests",
                        "body": (
                            "Update `tests/test_codex_orchestrate.py`.\n\n"
                            "## Acceptance Criteria\n- pytest passes\n"
                        ),
                        "labels": ["test"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    args = module.parse_args_from_list_for_test(
        [
            "1",
            "2",
            "--dry-run",
            "--issue-json",
            str(fixture),
            "--run-id",
            "test-run",
            "--runs-dir",
            str(tmp_path / "runs"),
        ]
    )
    issues = module.load_issues(args.issues, args.issue_json)
    analyses = [
        module.analyze_issue(issue, "photon-action-memory", skip_enhance=args.skip_enhance)
        for issue in issues
    ]
    run_dir = module.write_artifacts(args, analyses)

    assert (run_dir / "manifest.md").exists()
    assert (run_dir / "issue-analysis.md").exists()
    assert (run_dir / "dependency-plan.md").exists()
    assert "Issue #1" in (run_dir / "issue-analysis.md").read_text(encoding="utf-8")


def test_worktree_planning_does_not_mutate_in_dry_run() -> None:
    module = load_script()
    issue = module.Issue(
        number=3,
        title="Add worktree manager",
        body="Update `scripts/codex_orchestrate.py`.\n\n## Acceptance Criteria\n- dry-run only\n",
    )
    analysis = module.analyze_issue(issue, "photon-action-memory", skip_enhance=False)

    results = module.create_or_reuse_worktrees([analysis], dry_run=True)

    assert results[0].status == "planned"
    assert results[0].branch_name == "feature/issue-3-add-worktree-manager"


def test_commandmate_send_command_omits_agent_by_default() -> None:
    module = load_script()

    cmd = module.build_commandmate_send_command(
        "repo-issue-1",
        "hello",
        duration="3h",
        codex_agent_name="",
    )

    assert "--agent" not in cmd
    assert cmd == [
        "commandmatedev",
        "send",
        "repo-issue-1",
        "hello",
        "--auto-yes",
        "--duration",
        "3h",
    ]


def test_commandmate_worktree_id_uses_commandmate_branch_format() -> None:
    module = load_script()

    assert (
        module.commandmate_worktree_id("feature/issue-2-p0-m1-define-v1-sidecar-schema")
        == "photon-action-memory-feature-issue-2-p0-m1-define-v1-sidecar-schema"
    )


def test_poll_worker_startup_resumes_stuck_worker() -> None:
    module = load_script()
    calls: list[list[str]] = []

    def fake_runner(args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(args)
        if args == ["commandmatedev", "ls", "--json"] and len(calls) < 3:
            return module.subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "worktrees": [
                            {
                                "id": "repo-issue-1",
                                "status": "running",
                                "isProcessing": False,
                            }
                        ]
                    }
                ),
                "",
            )
        if args == ["commandmatedev", "ls", "--json"]:
            return module.subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "worktrees": [
                            {
                                "id": "repo-issue-1",
                                "status": "running",
                                "isProcessing": True,
                            }
                        ]
                    }
                ),
                "",
            )
        return module.subprocess.CompletedProcess(args, 0, "", "")

    result = module.poll_worker_startup(
        1,
        "repo-issue-1",
        codex_agent_name="",
        commands=("hello", "task"),
        runner=fake_runner,
    )

    assert result.status == "processing"
    assert ["commandmatedev", "send", "repo-issue-1", "a"] in calls


def test_render_uat_report_includes_manual_evidence() -> None:
    module = load_script()
    issue = module.Issue(
        number=4,
        title="GUI check",
        body="## Acceptance Criteria\n- Button is visible on device\n",
    )
    analysis = module.analyze_issue(issue, "photon-action-memory", skip_enhance=False)

    report = module.render_uat_report([analysis])

    assert "Manual GUI / Real-device Checks" in report
    assert "screenshot" in report


def test_render_uat_fix_prompts_maps_failure_to_issue() -> None:
    module = load_script()
    issue = module.Issue(
        number=5,
        title="Fix GUI regression",
        body="## Acceptance Criteria\n- GUI works\n",
    )
    analysis = module.analyze_issue(issue, "photon-action-memory", skip_enhance=False)
    failure = module.UatFailure(
        issue_number=5,
        scenario="Open settings",
        expected="Settings opens",
        actual="Blank screen",
        evidence="screenshot.png",
    )

    prompt = module.render_uat_fix_prompts([failure], [analysis])

    assert "UAT failure fix for Issue #5" in prompt
    assert "Blank screen" in prompt
    assert "feature/issue-5-fix-gui-regression" in prompt


def test_create_uat_fix_worktrees_dry_run() -> None:
    module = load_script()
    failure = module.UatFailure(5, "Open settings", "Settings opens", "Blank", "shot.png")

    results = module.create_uat_fix_worktrees([failure], dry_run=True)

    assert results[0].status == "planned"
    assert results[0].branch_name.startswith("fix/issue-5-uat-open-settings")


def test_photon_event_payload_redacts_paths_without_failing() -> None:
    module = load_script()

    result = module.emit_photon_event(
        "",
        event_kind="worker.blocked",
        run_id="run-1",
        payload={"path": "/Users/example/project/secret.txt"},
    )

    assert result.status == "skipped"
    assert module.sanitize_event_payload({"path": "/Users/example/project/secret.txt"}) == {
        "path": "[REDACTED_PATH]"
    }


def test_render_pr_body_contains_required_sections() -> None:
    module = load_script()
    issue = module.Issue(
        number=6,
        title="Add PR support",
        body=(
            "Update `scripts/codex_orchestrate.py`.\n\n"
            "## Acceptance Criteria\n- PR body lists tests\n"
        ),
    )
    analysis = module.analyze_issue(issue, "photon-action-memory", skip_enhance=False)

    body = module.render_pr_body(analysis, "run-1")

    assert "Closes #6" in body
    assert "## Tests Run" in body
    assert "run-1" in body
