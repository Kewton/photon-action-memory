---
name: codex-issue-worker
description: Implement one assigned issue in a dedicated git worktree.
---

# Codex Issue Worker

Use this skill inside a dedicated issue worktree after `/orchestrate` dispatches the issue.

## Required Flow

1. Read the issue summary, acceptance criteria, and orchestration notes.
2. Inspect the smallest relevant code surface.
3. Write `dev-reports/issue-<number>/design.md` before editing.
4. Implement the smallest coherent change.
5. Add or update focused tests when appropriate.
6. Run focused verification first.
7. Run broader verification when shared behavior or CI-sensitive code is touched.
8. Write `dev-reports/issue-<number>/implementation-summary.md`.
9. Write `dev-reports/issue-<number>/verification.md`.
10. Commit the change with a clear issue-scoped message.

Keep review lightweight. Ask only blocking questions.

