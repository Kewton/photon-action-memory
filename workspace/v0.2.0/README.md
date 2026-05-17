# PHOTON Action Memory v0.2.0 Plan

> 現在の実装状況はリポジトリ root の `README.md` と `docs/` を参照すること。
> このディレクトリは v0.2.0 計画の履歴資料であり、現行 sidecar の endpoint
> 実装状態や v0.4.0 LLM/PHOTON 設定の source of truth ではない。

## 目的

v0.2.0 の目的は、PHOTON Action Memory を v0.1.0 の **Action Memory Sidecar** から、より強い **Action Context Firewall** へ拡張することである。

v0.1.0 では、Coding Agent の tool loop、repo exploration、test result、past session から、次に読む file、実行する command、参照すべき evidence、避けるべき repeated action を提案する sidecar MVP を成立させる。

v0.2.0 では、これに加えて、agent の action によって発生する raw context を prompt に直接流さない。代わりに、tool/action 履歴を階層的な action state に圧縮し、agent には概要だけを渡し、必要時だけ evidence を展開する。

## 一文でのコンセプト

```
PHOTON Action Memory v0.2.0 is an Action Context Firewall
that compresses noisy coding-agent tool loops into compact,
evidence-grounded action states, and expands details only on demand.
```

日本語では次のように定義する。

> PHOTON Action Memory v0.2.0 は、  
> Coding Agent の tool/action loop から発生する raw context を隔離し、  
> やったこと・分かったこと・未解決のこと・避けるべきことを  
> 構造化 summary として保持し、  
> 必要時だけ evidence_id から詳細を展開する  
> **Action Context Firewall** である。

## v0.1.0 との差分

| 観点 | v0.1.0 | v0.2.0 |
|------|--------|--------|
| 中心機能 | next action / file / command / evidence の suggestion | context pollution を防ぐ Context Firewall |
| memory の役割 | L3 Action Memory Cache | L3 Action Memory Cache + Action Context Firewall |
| tool log の扱い | event store に蓄積し、suggestion に利用 | raw tool log は prompt 非注入を原則化 |
| summary | compact memory の初期機能 | ActionSummary を正式な中核 schema に昇格 |
| evidence | suggestion の根拠として返す | evidence_id として保持し、必要時だけ展開 |
| prompt 注入 | suggestion / evidence / warning を返す | ContextPack だけを prompt 注入対象にする |
| ranking | next action / file / evidence ranking | action ranking + context admission + evidence expansion ranking |
| evaluation | tool-call reduction, repeated exploration, hit rate | 追加で context pollution, summary fidelity, token saving を評価 |
| PHOTON らしさ | action/file/evidence scoring | hierarchical action state, recursive update, evidence-on-demand |

## v0.2.0 の中核

v0.2.0 の中核は次の 5 つである。

1. **ActionChunk** — tool events を action 単位に chunk 化する。
2. **ActionSummary** — やったこと、分かったこと、仮説、失敗、避けるべきこと、次の候補を構造化する。
3. **ContextPack** — 次の LLM prompt に入れる summary / warning / selected evidence を決める。
4. **Evidence-on-Demand** — summary だけで足りない場合に evidence_id から必要最小限の詳細だけ展開する。
5. **Summary Fidelity / Context Pollution Eval** — summary が raw event と整合しているか、不要な raw context を防げているか評価する。

## PHOTON 理論との対応

| PHOTON model | PHOTON Action Memory v0.2.0 |
|---|---|
| token-level sequence | tool/action/event sequence |
| low-rate contextual states | compact ActionSummary / SessionActionState |
| bottom-up compression | raw tool events → ActionChunk → ActionSummary |
| top-down reconstruction | evidence_id → selected evidence expansion |
| recursive generation | previous SessionActionState + new ActionChunk → updated state |
| multi-resolution scanning | summary / evidence snippet / raw local event の階層 |
| reduced KV-cache traffic | prompt に入る raw tokens の削減 |

重要なのは、単なる自然文要約ではないことである。

v0.2.0 では、summary は以下を満たす必要がある。

- evidence_id を持つ
- fact と hypothesis を分離する
- failed action と successful action を分離する
- stale 判定できる
- 必要時に raw evidence へ戻れる
- token budget と risk budget を持つ

## 完了定義

v0.2.0 は、以下を満たしたら完了とする。

1. raw tool output が default で prompt に入らない。
2. prompt-visible memory は ContextPack 経由のみになる。
3. ActionSummary が以下を分離して持つ。
   - `actions_done`
   - `facts`
   - `hypotheses`
   - `failed_attempts`
   - `avoid`
   - `next_hints`
4. facts / hypotheses / failed_attempts は `evidence_ids` を持つ。
5. evidence は必要時だけ `/v1/evidence/expand` で展開される。
6. stale summary が commit hash / file fingerprint / timestamp で無効化される。
7. ContextPack が token budget を守る。
8. full transcript context と比べて `tokens_saved_vs_raw` を測定できる。
9. `summary_fidelity` を測定できる。
10. `raw_tool_tokens_in_prompt` を測定できる。
11. Anvil shadow-mode で ContextPack の採用・無視・結果を追跡できる。
12. PHOTON model unavailable 時は deterministic fallback に戻る。
13. sidecar failure 時も agent 本体は fail-open で継続する。

## ドキュメント構成

```
workspace/v0.2.0/
├── README.md
├── 01_concept_and_delta.md
├── 02_requirements_and_scope.md
├── 03_schema_and_api.md
├── 04_architecture.md
├── 05_evaluation.md
└── 06_work_plan.md
```
