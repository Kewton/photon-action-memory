# Design Note — Issue #31: Materialize v0.2.0 Docs and Schema Diff

## Issue

[P0][v0.2][M0] Materialize v0.2.0 docs and schema diff

## Objective

Expand `workspace/v0.2.0/plan.md` into formal v0.2.0 documentation defining the Action Context Firewall. M0 is a documentation-only milestone; no implementation code is changed.

## Source

All content derives from `workspace/v0.2.0/plan.md`, which contains the complete v0.2.0 design authored by the project. The plan embeds shell heredoc commands that define the target file content. This task materializes those files as proper Markdown documents.

## Design Decisions

### 1. Documentation-only scope

M0 produces docs only. No Python source files are created or modified. The schema definitions in `03_schema_and_api.md` are JSON examples for documentation purposes, not implemented code.

### 2. Markdown formatting over raw text

The plan.md content is structured as plain text with implicit sections. The materialized docs apply Markdown formatting (headers, tables, code blocks, lists) to make the content navigable and readable on GitHub.

### 3. File boundaries match plan.md

Each file maps directly to a `cat > workspace/v0.2.0/<file> <<'EOF'` block in plan.md. No content is invented or added beyond what plan.md specifies.

### 4. Dev-reports are issue-scoped

`dev-reports/issue-31/` contains three files:
- `design.md` — this document
- `implementation-summary.md` — what was written and why
- `verification.md` — acceptance criteria check

## Key Design Points from plan.md

### Action Context Firewall

v0.2.0 reframes the sidecar from "suggest next action" to "control what enters the prompt." The firewall enforces:

- raw tool output does not enter the prompt by default
- only ContextPack items are prompt-visible
- evidence is referenced by ID and expanded only on demand

### Central schemas

| Schema | Role |
|--------|------|
| ActionChunk | Groups tool events into meaningful action units |
| ActionSummary | Structured summary with facts/hypotheses/failed_attempts separated |
| EvidenceRef | Pointer to evidence that can be expanded on demand |
| ContextPack | The only memory allowed into the LLM prompt |
| ContextAdmissionDecision | Records each admit/omit/deny decision |

### Raw tool log non-admission policy

The default admission policy is:

```yaml
raw_evidence_policy: deny_by_default
allow_full_stdout: false
allow_full_stderr: false
allow_full_file_content: false
allow_stale_summary: false
allow_ungrounded_fact: false
```

This is the defining invariant of v0.2.0.

### v0.3.0 deferral

MCP/stdio adapter, multi-agent coordination, and online learning are explicitly deferred to v0.3.0+. This keeps M0 scope clean.
