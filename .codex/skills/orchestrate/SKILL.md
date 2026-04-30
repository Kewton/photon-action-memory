---
name: orchestrate
description: Plan and run Codex issue orchestration through CommandMate and git worktrees.
---

# Codex Orchestrate

Use this skill when the user asks to run `/orchestrate <issue...>` for this repository.

## Operating Rules

- Start from the develop integration worktree.
- Keep Issue enhancement lightweight; ask only blocking questions.
- Use `origin/develop` as the base for planned worktrees.
- Prefer repository-local artifacts under `workspace/management/runs/`.
- Do not delete, reset, or overwrite existing worktrees without explicit user approval.
- Do not merge PRs with failing CI unless the user explicitly approves.
- Include manual UAT steps when GUI or real-device confirmation is needed.

## First Action

Run the dry-run planner first:

```bash
python scripts/codex_orchestrate.py <issue...> --dry-run
```

Review the generated:

- `workspace/management/runs/<run_id>/manifest.md`
- `workspace/management/runs/<run_id>/issue-analysis.md`
- `workspace/management/runs/<run_id>/dependency-plan.md`

Proceed to worktree creation and CommandMate dispatch only after the plan is coherent and any blocking questions have been answered.

