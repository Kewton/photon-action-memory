---
name: codex-create-pr
description: Create a develop-targeted pull request for the current issue worktree.
---

# Codex Create PR

Use this skill after an issue worker has committed verified changes.

## Required PR Body

Include:

- linked Issue
- summary
- changed files
- tests run
- known risks
- orchestration run ID when available

Do not create a duplicate PR if an open PR already exists for the current branch.

