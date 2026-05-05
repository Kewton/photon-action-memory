# 02. Requirements and Scope

## 1. Goal

v0.2.0 の goal は次である。

PHOTON Action Memory を Action Context Firewall として拡張し、Coding Agent の tool/action loop から発生する raw context を prompt から隔離し、summary-only default と evidence-on-demand によって、token cost、context pollution、repeated exploration、failed retry を削減する。

## 2. In Scope

- ActionChunk schema
- ActionSummary schema
- EvidenceRef schema
- ContextPack schema
- ContextAdmissionDecision schema
- SummaryValidationResult schema
- StalenessPolicy schema
- `POST /v1/context/pack` API
- `POST /v1/evidence/expand` API
- `POST /v1/summary/validate` API
- `/v1/summarize` の v0.2.0 schema 拡張
- raw tool log non-admission policy
- Context Admission Controller
- Evidence Expander
- Summary Fidelity Checker
- Staleness Guard
- Token Budget Manager
- Context Pollution Metrics
- Anvil prompt construction 前の shadow-mode integration
- deterministic fallback for context packing
- PHOTON context scoring interface
- local LLM oriented eval metrics

## 3. Out of Scope

以下は v0.2.0 の対象外とし、v0.3.0 以降で扱う。

- main coding agent の置き換え
- final answer generation
- destructive command の自動承認
- edit command の自動承認
- remote multi-tenant SaaS 前提の運用
- raw secret / token / private path の保存
- raw transcript を常時 prompt に入れる設計
- online learning による即時モデル更新
- **MCP / stdio adapter の本格実装** (→ v0.3.0)
- multi-agent coordination
- repository index / vector DB / graph DB のフル実装

## 4. Functional Requirements

### FR-1: Event ingestion

`POST /v1/events` は v0.1.0 から継続する。

追加要件:

- sanitizer を event store 前に必ず通す
- raw output は保存前に redaction される
- raw output の prompt admission は **default deny**
- event は ActionChunk の材料になる

### FR-2: Action chunking

複数の EventRecord を action 単位にまとめる。

例:

- repo-wide search chunk
- file inspection chunk
- failure reproduction chunk
- edit attempt chunk
- test verification chunk
- answer preparation chunk

### FR-3: Action summary

ActionChunk から ActionSummary を生成する。

ActionSummary は以下を分離する。

- `actions_done`
- `facts`
- `hypotheses`
- `failed_attempts`
- `avoid`
- `next_hints`
- `evidence_refs`
- `staleness`

### FR-4: Context pack generation

`POST /v1/context/pack` は、次の LLM prompt に入れる memory を返す。

```
Input:
  current task
  working memory
  recent events
  action summaries
  token budget
  admission policy
Output:
  ContextPack
```

### FR-5: Evidence expansion

`POST /v1/evidence/expand` は evidence_id から必要最小限の detail を返す。

制約:

- `max_expand_chars` を守る
- sanitizer を再適用する
- raw output 全文は返さない
- selected snippet / line range / summarized stderr のみ返す

### FR-6: Summary validation

`POST /v1/summary/validate` は、summary が raw events と整合しているか検証する。

検証対象:

- evidence_id が存在するか
- fact が evidence に支えられているか
- hypothesis が fact と混ざっていないか
- summary が stale でないか
- file fingerprint が変わっていないか
- failed action が successful action として扱われていないか

### FR-7: Suggestion compatibility

`POST /v1/suggest` は v0.1.0 と互換を保つ。

追加要件:

- suggest response は ContextPack と連携できる
- suggestion は context admission の結果を参照できる
- evidence は EvidenceRef として返す

## 5. Non-functional Requirements

| 項目 | 要件 |
|------|------|
| Local-first | default は localhost / local state のみ |
| Fail-open | sidecar failure 時に agent 本体を止めない |
| Low latency | no-model context pack は p50 200ms 未満を目標 |
| Model optional | PHOTON model unavailable 時は deterministic fallback |
| Privacy | raw secret / token / private home path を保存しない |
| Prompt hygiene | raw tool output は default deny |
| Determinism | fallback packing は deterministic |
| Observability | admission / omission / expansion / outcome を記録 |
| Compatibility | Anvil 以外の agent にも使える neutral schema |
| Local LLM friendly | context budget を小さく固定できる |

## 6. Admission Policy

### Default policy

```yaml
raw_evidence_policy: deny_by_default
default_detail_level: summary_only
allow_selected_snippet: true
allow_full_stdout: false
allow_full_stderr: false
allow_full_file_content: false
allow_stale_summary: false
allow_ungrounded_fact: false
```

### Allowed prompt-visible memory

- task summary
- current constraints
- action summary
- fact with `evidence_id`
- hypothesis with `evidence_id` and status
- avoid guidance
- warning
- selected evidence snippet

### Denied prompt-visible memory

- raw grep output
- raw ripgrep output
- full test stdout
- full build log
- repeated failed command output
- full file content
- secret-like string
- absolute home path
- token-like value
- stale summary
- ungrounded fact

## 7. Local LLM Specific Requirements

v0.2.0 は local LLM 特化 coding agent で特に価値を出す。

追加要件:

- `max_memory_tokens` を明示的に設定できる
- `prompt_tokens_per_turn` を記録する
- context pack tokens を記録する
- `tokens_saved_vs_full_transcript` を記録する
- `prefill_time_ms` を外部 agent から optional に受け取れる
- `peak_vram_mb` を external metric として紐づけられる
- model size / quantization / context length を eval metadata に残せる
