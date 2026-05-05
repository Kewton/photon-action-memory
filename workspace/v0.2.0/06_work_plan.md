# 06. Work Plan

## 1. Goal

v0.2.0 の goal は、PHOTON Action Memory に Action Context Firewall を実装し、summary-only default と evidence-on-demand によって、Coding Agent の prompt を汚さずに長時間 tool loop を支えること。

## 2. Milestones

### M0: v0.2.0 documentation and schema diff

成果物:

```
workspace/v0.2.0/README.md
workspace/v0.2.0/01_concept_and_delta.md
workspace/v0.2.0/02_requirements_and_scope.md
workspace/v0.2.0/03_schema_and_api.md
workspace/v0.2.0/04_architecture.md
workspace/v0.2.0/05_evaluation.md
workspace/v0.2.0/06_work_plan.md
```

完了条件:

- v0.1.0 との差分が明文化されている
- Action Context Firewall の定義がある
- raw tool log non-admission policy がある
- ActionSummary / EvidenceRef / ContextPack の schema がある

### M1: Schema implementation

成果物:

- ActionChunk schema
- ActionSummary schema
- EvidenceRef schema
- ContextPack schema
- ContextAdmissionDecision schema
- SummaryValidationResult schema
- StalenessPolicy schema
- JSON fixture tests

完了条件:

- all schemas have `schema_version`
- optional unknown fields do not break validation
- missing required fields produce validation error
- fact / hypothesis / failed_attempt / avoid can be represented separately

### M2: Action chunking and summary builder

成果物:

- ActionChunker
- ActionSummaryBuilder
- SummaryCanonicalizer
- SummaryStateUpdater
- deterministic summary fallback

完了条件:

- recent EventRecords can be grouped into ActionChunk
- ActionChunk can produce ActionSummary
- all facts have `evidence_ids`
- failed actions are not misclassified as successful actions
- previous summary can be updated incrementally

### M3: ContextPack API

成果物:

- `POST /v1/context/pack`
- ContextAdmissionController
- TokenBudgetManager
- PromptPackRenderer
- admission / omission logging

完了条件:

- summary-only ContextPack can be returned
- raw tool output is omitted by default
- `max_memory_tokens` is enforced
- `tokens_saved_vs_raw` is computed
- sidecar remains fail-open

### M4: Evidence-on-demand

成果物:

- `POST /v1/evidence/expand`
- EvidenceExpander
- snippet selector
- redaction re-check
- expansion logging

完了条件:

- `evidence_id` can be expanded into selected snippet
- full raw output is denied by default
- `max_expand_chars` is enforced
- sanitizer runs before response

### M5: Summary validation and staleness guard

成果物:

- `POST /v1/summary/validate`
- SummaryFidelityChecker
- StalenessGuard
- file fingerprint tracker
- contradiction detector, minimal version

完了条件:

- missing `evidence_id` is detected
- stale summary is detected on commit/file change
- hypothesis-as-fact issue is detected
- `summary_fidelity` metric is computed

### M6: Evaluation

成果物:

- context pollution metrics
- summary fidelity metrics
- local LLM metrics hooks
- offline replay runner
- aggregate eval report

完了条件:

- full transcript vs summary-only vs summary+evidence can be compared
- `raw_tool_tokens_in_prompt` is reported
- `tokens_saved_vs_full_transcript` is reported
- `repeated_exploration_rate` is reported
- `failed_action_retry_rate` is reported
- eval report contains no raw logs/prompts/tool outputs

### M7: Anvil shadow integration

成果物:

- Anvil context pack integration contract
- prompt construction hook proposal
- context pack fixture
- evaluate request fixture
- canary mode config

完了条件:

- Anvil can call `/v1/context/pack` before LLM prompt construction
- Anvil can call `/v1/evidence/expand` when detail is needed
- ContextPack adoption / ignored / outcome can be logged
- only low-risk context injection is enabled in canary

### M8: PHOTON context scoring

成果物:

- `context_admission_score` interface
- `evidence_expansion_score` interface
- `summary_usefulness_score` interface
- `staleness_risk_score` interface
- deterministic fallback comparison

完了条件:

- model unavailable path works
- PHOTON scorer can be plugged in
- scoring path has smoke tests
- fallback and PHOTON scoring can be compared in eval

## 3. Issue Breakdown

| Priority | Issue | Description |
|----------|-------|-------------|
| P0 | Define v0.2 schema models | ActionChunk, ActionSummary, EvidenceRef, ContextPack |
| P0 | Add JSON fixtures | valid/invalid fixtures for new schemas |
| P0 | Implement ActionChunker | group events into action chunks |
| P0 | Implement ActionSummaryBuilder | structured summary with evidence_ids |
| P0 | Implement ContextPack API | prompt-visible memory pack |
| P0 | Enforce raw tool log default deny | admission policy |
| P1 | Implement EvidenceExpander | evidence_id to selected snippet |
| P1 | Implement SummaryValidation | fidelity and grounding checks |
| P1 | Implement StalenessGuard | commit/file fingerprint based invalidation |
| P1 | Add context pollution metrics | raw_tool_tokens, tokens_saved |
| P1 | Add eval runner update | compare full transcript vs summary modes |
| P2 | Add Anvil integration contract | context pack before prompt |
| P2 | Add local LLM metrics hooks | prefill, vram, context length metadata |
| P2 | Add PHOTON context scorer | context admission / expansion scoring |
| P2 | Add canary config | low-risk injection only |

## 4. Recommended Implementation Order

1. docs
2. schema
3. fixtures
4. sanitizer policy update
5. ActionChunker
6. ActionSummaryBuilder
7. ContextPack API
8. EvidenceExpander
9. SummaryValidation
10. StalenessGuard
11. eval metrics
12. Anvil shadow integration
13. PHOTON context scorer

理由:

- schema が先にないと integration と eval が進まない
- sanitizer policy は event store / evidence expansion 前に固める必要がある
- ContextPack は v0.2.0 の中心 API
- EvidenceExpander は ContextPack の後に実装する方が自然
- PHOTON scorer は deterministic fallback の後でよい

## 5. Risk and Mitigation

| Risk | Mitigation |
|------|------------|
| summary が過圧縮して重要 detail を失う | evidence-on-demand と `detail_needed_but_missing_rate` を測る |
| summary が嘘を含む | `evidence_ids` 必須、`summary_fidelity` を測る |
| hypothesis が fact と混ざる | schema で facts / hypotheses を分離する |
| stale summary が prompt に入る | StalenessGuard で default deny |
| prompt がうるさくなる | `max_memory_tokens` と admission threshold |
| PHOTON model が未成熟 | deterministic fallback を維持 |
| context pack が遅い | no-model path p50 200ms 目標 |
| raw secret が漏れる | sanitizer before store + before expand |
| Anvil 専用になる | neutral schema + adapter |
| eval report に raw logs が混ざる | aggregate-only report policy |

## 6. v0.2.0 Release Checklist

- [ ] workspace/v0.2.0 docs committed
- [ ] v0.2 schema implemented
- [ ] JSON fixtures added
- [ ] sanitizer policy updated
- [ ] ActionChunker implemented
- [ ] ActionSummaryBuilder implemented
- [ ] ContextPack API implemented
- [ ] EvidenceExpander implemented
- [ ] SummaryValidation implemented
- [ ] StalenessGuard implemented
- [ ] Context pollution metrics added
- [ ] Offline eval updated
- [ ] Anvil shadow contract drafted
- [ ] deterministic fallback passes tests
- [ ] model-unavailable path passes tests
- [ ] raw tool output default deny tested
- [ ] fail-open behavior tested
- [ ] privacy regression tested

## 7. v0.3.0 Candidates

v0.2.0 で扱わず、v0.3.0 以降に送る候補:

- MCP / stdio adapter
- multi-agent memory sharing
- repo-local continuous adaptation
- online learning with rollback
- richer graph index integration
- cross-repo action pattern transfer
- auto-generated eval tasks
- production canary dashboards
