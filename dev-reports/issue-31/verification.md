# Verification — Issue #31

## Acceptance Criteria Check

### AC-1: v0.1.0 delta is clearly documented

**Status: PASS**

`workspace/v0.2.0/README.md` contains a comparison table across 9 dimensions (中心機能, memory の役割, tool log の扱い, summary, evidence, prompt 注入, ranking, evaluation, PHOTON らしさ).

`workspace/v0.2.0/01_concept_and_delta.md` documents the delta with:
- the problem (action-induced context pollution)
- v0.1.0 vs v0.2.0 question/output comparison
- 10 invariants that are new in v0.2.0

### AC-2: Action Context Firewall is defined

**Status: PASS**

The concept is defined in `workspace/v0.2.0/README.md`:

> PHOTON Action Memory v0.2.0 is an Action Context Firewall that compresses noisy coding-agent tool loops into compact, evidence-grounded action states, and expands details only on demand.

`workspace/v0.2.0/01_concept_and_delta.md` expands this with the basic policy (default: summary-only, denied: raw tool output) and 10 invariants.

`workspace/v0.2.0/04_architecture.md` defines the Context Admission Controller as the architectural component enforcing the firewall.

### AC-3: raw tool log non-admission policy is documented

**Status: PASS**

`workspace/v0.2.0/02_requirements_and_scope.md` section 6 (Admission Policy) defines:

```yaml
raw_evidence_policy: deny_by_default
allow_full_stdout: false
allow_full_stderr: false
allow_full_file_content: false
allow_stale_summary: false
allow_ungrounded_fact: false
```

The denied list explicitly names: raw grep output, raw ripgrep output, full test stdout, full build log, repeated failed command output, full file content, secret-like string, absolute home path, token-like value, stale summary, ungrounded fact.

### AC-4: ActionSummary / EvidenceRef / ContextPack schemas are documented

**Status: PASS**

`workspace/v0.2.0/03_schema_and_api.md` defines all schemas with JSON examples:

| Schema | Section |
|--------|---------|
| ActionChunk | Section 3 |
| EvidenceRef | Section 4 |
| ActionSummary | Section 5 |
| ContextAdmissionDecision | Section 6 |
| ContextPack | Section 7 |

All schemas include `schema_version: "action-memory.v0.2"`.

ActionSummary separates: `actions_done`, `facts`, `hypotheses`, `failed_attempts`, `avoid`, `next_hints`, `token_cost`, `validity`.

### AC-5: v0.3.0+ deferred scope is explicit

**Status: PASS**

`workspace/v0.2.0/02_requirements_and_scope.md` section 3 (Out of Scope) explicitly lists deferred items including MCP/stdio adapter.

`workspace/v0.2.0/06_work_plan.md` section 7 (v0.3.0 Candidates) lists 8 items deferred to v0.3.0+:
- MCP / stdio adapter
- multi-agent memory sharing
- repo-local continuous adaptation
- online learning with rollback
- richer graph index integration
- cross-repo action pattern transfer
- auto-generated eval tasks
- production canary dashboards

## Expected Files Check

| File | Status |
|------|--------|
| `workspace/v0.2.0/README.md` | Created |
| `workspace/v0.2.0/01_concept_and_delta.md` | Created |
| `workspace/v0.2.0/02_requirements_and_scope.md` | Created |
| `workspace/v0.2.0/03_schema_and_api.md` | Created |
| `workspace/v0.2.0/04_architecture.md` | Created |
| `workspace/v0.2.0/05_evaluation.md` | Created |
| `workspace/v0.2.0/06_work_plan.md` | Created |
| `dev-reports/issue-31/design.md` | Created |
| `dev-reports/issue-31/implementation-summary.md` | Created |
| `dev-reports/issue-31/verification.md` | Created |

## Result

All 5 acceptance criteria: **PASS**  
All 10 expected files: **Created**
