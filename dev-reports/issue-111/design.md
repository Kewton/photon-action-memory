# Issue #111 Design

## Goal

Add universal applicability scope for language/framework/tool-wide seeds that
can be retrieved independently of repo_id and task_signature.

## Schema

`ActionSummary` accepts schema versions `action-memory.v0.2` and
`action-memory.v0.3`. Existing summaries default to:

```text
applicability_scope = "repo"
universal_metadata = None
```

Universal summaries set:

```text
applicability_scope = "universal"
universal_metadata = { language, framework, tool, os, severity, token_budget_cap }
```

## Retrieval

Universal retrieval is Stage 4 after repo-specific and common seed retrieval:

1. repo + task_signature
2. repo fallback
3. `__common__` + task_signature
4. universal scope filtered by detected language/framework/tool/os

`detect_universal_filters()` extracts filters from task text and touched files.
The Stage 4 selector enforces:

- max 5 universal summaries,
- max 500 estimated tokens total,
- per-seed `universal_metadata.token_budget_cap`.

Universal summaries still pass through the normal ContextPack admission and
quality gate, including prompt-visible secret masking and next_hint suppression.

## CLI

`photon-seed-add` is registered as a project script and can set scope and
metadata:

```bash
photon-seed-add \
  --fixture tests/fixtures/shared/universal_pytest_verbose_action_summary.json \
  --scope universal \
  --metadata-json '{"language":["python"],"framework":["pytest"]}'
```

## Seed Set

`scripts/seed_universal_seeds.sh` seeds 10 initial universal fixtures covering
Python, Rust, Node, SvelteKit, Git, and macOS/MLX guidance.
