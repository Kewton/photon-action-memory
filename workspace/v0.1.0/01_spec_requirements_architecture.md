# 仕様、要件、アーキテクチャ

## 1. 位置づけ

`photon-action-memory` は、Coding Agent 向けの **L3 Action Memory Cache** である。

CPU のメモリ階層に例えると、次の位置に置く。

```text
LLM internal state
  ↓
Prompt / Context Window            L1
  ↓
Agent Working Memory               L2
  ↓
PHOTON Action Memory               L3
  ↓
Episodic / User Memory             Main Memory
  ↓
Repo Index / Vector DB / Graph     Storage
```

PHOTON Action Memory は、過去情報を保存するだけではなく、現在の agent state から **次に取るべき行動候補** を返す。

## 2. 解く問題

Coding Agent は、実装や調査の途中で以下の無駄を起こしやすい。

- 同じ file / symbol / command を何度も探索する
- 既に失敗した方針を再試行する
- 必要な test / build / grep に到達するまでが遅い
- session を跨ぐと repo 固有の知見を失う
- context window に入れる情報の選別が粗い
- Plan / Act の意図から作業が逸れる

本リポジトリが解く問題は次の 1 文に集約する。

> 現在の task state、repo state、tool results、過去 session から、Coding Agent の次の一手を改善する。

## 3. v0.1.0 のスコープ

### In Scope

- local-first sidecar API
- action memory request / response schema
- event store への agent trajectory 蓄積
- sanitized training dataset export
- next action / target file / evidence 候補の ranking
- Anvil からの shadow-mode 呼び出しを想定した API
- offline eval 用の dataset / metrics 定義
- fail-open integration contract

### Out of Scope

- Agent 本体の置き換え
- final answer generation
- 汎用 user memory
- 汎用 document RAG
- vector DB / graph DB のフル実装
- 自動オンライン学習による即時モデル更新
- secret を含む raw log の保存や学習
- remote multi-tenant SaaS 前提の運用

## 4. 主要ユースケース

| ユースケース | PHOTON Action Memory の役割 |
| --- | --- |
| Repo 調査開始 | 最初に読むべき file / directory / symbol を提示する |
| バグ修正 | error output から疑わしい file、test、既知ケースを返す |
| 実装タスク | 類似変更の探索先、編集前に読むべき周辺 file を返す |
| テスト失敗解析 | failure pattern から次の command / evidence を推薦する |
| Plan / Act | plan から逸れている可能性や、未回収の evidence を警告する |
| session resume | 前回 session の探索結果を action guidance として復元する |

## 5. 機能要件

### 5.1 Sidecar API

v0.1.0 では HTTP localhost を主経路とし、将来 stdio / MCP adapter を追加できる形にする。

必須 endpoint:

| Endpoint | 目的 |
| --- | --- |
| `GET /health` | sidecar 稼働確認 |
| `POST /v1/events` | tool call / file read / edit / test result などを蓄積 |
| `POST /v1/suggest` | 現在状態から action guidance を返す |
| `POST /v1/summarize` | session / tool loop を compact memory に変換 |
| `POST /v1/evaluate` | shadow-mode の suggestion と実行結果を記録 |

M2 MVP では `summarize` / `evaluate` は `501 Not Implemented` を返し、
contract のみ固定する。実体は M6 の shadow eval 実装で追加する。

### 5.2 Suggest Request

最小 schema:

```json
{
  "request_id": "uuid-or-agent-turn-id",
  "agent": {
    "name": "anvil",
    "version": "0.1.x"
  },
  "repo": {
    "root": "/path/to/repo",
    "name": "Anvil",
    "branch": "feature/example",
    "commit": "HEAD-or-sha"
  },
  "task": {
    "user_request": "Fix failing test...",
    "mode": "plan|act|answer",
    "summary": "short task summary"
  },
  "working_memory": {
    "active_task": "...",
    "constraints": [],
    "touched_files": [],
    "unresolved_errors": [],
    "active_precautions": []
  },
  "recent_events": [
    {
      "type": "tool_result",
      "tool": "grep",
      "status": "success",
      "summary": "found symbol in src/session/store.rs"
    }
  ],
  "budget": {
    "max_suggestions": 8,
    "max_evidence_chars": 4000
  }
}
```

### 5.3 Suggest Response

最小 schema:

```json
{
  "request_id": "same-as-request",
  "model_version": "photon-action-memory-v0.1.0",
  "suggestions": [
    {
      "kind": "read|search|edit|test|build|inspect|ask_user|answer|replan",
      "target": "src/session/store.rs",
      "command": null,
      "query": null,
      "confidence": 0.72,
      "reason": "working memory and recent errors point to session persistence",
      "evidence_ids": ["evt_001", "case_012"]
    }
  ],
  "evidence": [
    {
      "id": "evt_001",
      "kind": "tool_result",
      "summary": "recent grep found WorkingMemory serialization path",
      "source": "session"
    }
  ],
  "warnings": [
    {
      "kind": "drift|repeat_failure|missing_evidence",
      "message": "similar search was already attempted twice"
    }
  ]
}
```

### 5.4 Shadow Evaluation Contract

Anvil は shadow-mode では suggestion を受け取るが、最終判断は agent loop 側で行う。
`POST /v1/evaluate` は、その判断結果を後から評価できるように以下を記録する。

```json
{
  "schema_version": "action-memory.v1",
  "request_id": "anvil-shadow-eval-0001",
  "session_id": "anvil-session-20260430",
  "records": [
    {
      "request_id": "anvil-shadow-req-0001",
      "suggestion_ids": [
        "sug-read-turn-loop",
        "sug-read-session-store"
      ],
      "actual_next_action": {
        "kind": "read",
        "target": "src/agent/loop_run/turn.rs",
        "summary": "Read the actor loop before editing"
      },
      "matched": true,
      "ignored_reason": null,
      "outcome": "success",
      "latency_ms": 184.2,
      "sidecar_status": "ok"
    }
  ]
}
```

contract fixture:

- `tests/fixtures/anvil_shadow_mode/suggest_request.json`
- `tests/fixtures/anvil_shadow_mode/suggest_response.json`
- `tests/fixtures/anvil_shadow_mode/event_request.json`
- `tests/fixtures/anvil_shadow_mode/evaluate_request.json`

integration spec:

- `workspace/v0.1.0/anvil_shadow_mode_contract.md`

これにより request id、suggestion ids、actual next action、matched、
ignored reason、outcome、latency、sidecar status を固定 schema で追跡する。

## 6. 非機能要件

| 項目 | 要件 |
| --- | --- |
| Local-first | default は localhost / local state のみ |
| Fail-open | sidecar failure 時に agent 本体を止めない |
| Low latency | `POST /v1/suggest` は p50 200ms 未満を目標、MLX 推論ありでも p50 1s 未満を初期目標 |
| Privacy | raw secret / absolute home path / token を保存しない |
| Determinism | schema validation、sanitizer、ranking fallback はテスト可能にする |
| Observability | suggestion、agent action、outcome を紐づけて shadow eval できる |
| Compatibility | Anvil 以外の agent からも使える neutral schema にする |

## 7. 論理アーキテクチャ

```text
Coding Agent
  ├── sends events
  └── asks suggestions
        ↓
PHOTON Action Memory Sidecar
  ├── API Layer
  ├── Schema Validator
  ├── Sanitizer
  ├── Event Store
  ├── Session Memory Builder
  ├── Candidate Retriever
  ├── PHOTON Model Adapter
  ├── Action Ranker
  └── Eval Logger
        ↓
Local State
  ├── events.sqlite
  ├── cases.jsonl
  ├── compact_memory.jsonl
  ├── eval_runs/
  └── model_cache/
```

## 8. 推奨パッケージ構成

```text
photon-action-memory/
├── photon_action_memory/
│   ├── api/
│   │   ├── schema.py
│   │   └── server.py
│   ├── memory/
│   │   ├── store.py
│   │   ├── sanitizer.py
│   │   └── compaction.py
│   ├── ranking/
│   │   ├── candidates.py
│   │   └── ranker.py
│   ├── models/
│   │   ├── photon_adapter.py
│   │   └── fallback.py
│   ├── training/
│   │   ├── exporters/
│   │   └── datasets.py
│   └── eval/
│       ├── metrics.py
│       └── runner.py
├── scripts/
├── tests/
├── configs/
└── workspace/
```

## 9. データモデル

### Event

Agent から送られる最小単位。

- `event_id`
- `session_id`
- `turn_id`
- `repo_id`
- `timestamp`
- `event_type`
- `tool_name`
- `status`
- `summary`
- `artifacts`
- `redaction_status`

### Case

再利用可能な成功・失敗パターン。

- `case_id`
- `task_signature`
- `repo_fingerprint`
- `language_stack`
- `initial_state`
- `action_sequence`
- `outcome`
- `quality_score`
- `precautions`

### Suggestion

Agent に返す action guidance。

- `kind`
- `target`
- `command`
- `query`
- `confidence`
- `reason`
- `evidence_ids`
- `risk`

## 10. 評価指標

v0.1.0 では、最終回答品質よりも agent loop 改善を測る。

| 指標 | 意味 |
| --- | --- |
| first-useful-file hit rate | 初期 suggestion が実際に有用 file に当たった割合 |
| tool-call reduction | task 完了までの tool 呼び出し削減率 |
| repeated exploration rate | 同一 search/read の重複率 |
| test/build time-to-first | 最初の有効 test/build までの時間 |
| failed-action retry rate | 失敗済み action を再試行した割合 |
| context evidence precision | context に入れた evidence が最終判断に寄与した割合 |
| fail-open incident count | sidecar 障害が agent 本体を止めた件数 |

## 11. Anvil 統合ポイント

Anvil 側では以下の箇所が初期候補になる。

- `src/session/store.rs`
  - `WorkingMemory` を request の L2 state として渡す
- `src/session/case_retrieval.rs`
  - lexical case retrieval の semantic/action rerank として PHOTON を使う
- `src/agent/loop_run/turn.rs`
  - actor loop の前に `POST /v1/suggest`
  - tool result 後に `POST /v1/events`
- `src/agent/prompting.rs`
  - Repo Context v2 の evidence selection に使う

## 12. 設計原則

- PHOTON は final decision maker ではなく advisor とする。
- agent は suggestion を無視できる。
- sidecar は落ちてもよい。
- raw log より normalized action trajectory を優先する。
- 学習対象は文章ではなく、状態から行動への写像にする。
- evaluation を通過した model のみ default に昇格する。
