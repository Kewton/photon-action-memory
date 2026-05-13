# Design Note — Issue #84

## Objective

PHOTON Action Memory の中核は「raw tool/action 履歴 → 階層的な action state →
prompt には summary-only context」というパイプライン。本 P0 では未完成な
階層連携を `/v1/summarize` 経由で繋ぎ、`/v1/context/pack` が階層 summary を
正しく取得・配布できるようにする。

## Acceptance criteria revisited

1. `/v1/summarize` 後に `summary_level=turn/session/case` の summary を保存できる。
2. `/v1/context/pack` が repo/task に応じて該当 summary を取得する。
3. prompt-visible item は summary-only であり、raw event は入らない。
4. `tokens_saved_vs_raw` が response または stored summary から確認できる。

## Current state

- `/v1/summarize` は 501 stub (`api/server.py:240`).
- `/v1/summary/upsert` は seed-summary を `SummaryStore` に書き込めるが、
  チャンクから階層 summary を生成する経路は無い。
- `/v1/context/pack` は `SummaryRetriever.search(repo_id=…, task_signature=…)`
  で既に repo/task scoping を行い、`mode="summary_only"`/raw 拒否ポリシーで
  prompt から raw event を排除している (`context/pack.py:48`).
- `TokenBudget.tokens_saved_vs_raw` は admission ループで `add_raw` 経由で
  集計済み (`context/budget.py:31`) — response にも乗っている。
- `ActionSummaryBuilder` と `SummaryStateUpdater` はチャンク→summary 化を
  既に実装済み (`memory/summaries.py`).

## Scope of this change

最小で受け入れ条件 #1 を満たし、#2–#4 の振る舞いを assertion で固定する。
新規モデル/抽象は導入しない。

### `/v1/summarize` の実装

Request:

```json
{
  "schema_version": "action-memory.v0.2",
  "request_id": "summarize_001",
  "session_id": "sess_001",
  "repo_id": "photon-test",
  "task_signature": "live-codename-task",
  "summary_level": "turn|session|case|chunk",
  "chunks": [ActionChunk, …],
  "policy": { … }   // forward-compatible; ignored in M2
}
```

Response:

```json
{
  "schema_version": "action-memory.v0.2",
  "request_id": "summarize_001",
  "summary": ActionSummary,           // 永続化済み・summary_level 上書き済み
  "validation": SummaryValidationResult,
  "tokens_saved_vs_raw": int,
  "sidecar_status": "ok|degraded",
  "warnings": [ContextPackWarning]
}
```

処理:

1. `chunks` を ActionSummaryBuilder で 1-by-1 サマリ化。
2. `SummaryStateUpdater` で先頭 summary に畳み込み、階層 state にする。
3. 結果に対し `summary_level` / `session_id` / `repo_id` / `task_signature`
   を request 値で上書き。
4. `SummaryFidelityChecker.check(...)` で validation。
5. `SummaryStore.upsert(...)` で永続化。
6. `token_cost.tokens_saved_vs_raw` を response にもサーフェスする。

エラー時は 5xx を投げず、`sidecar_status="degraded"` + warnings を載せた
空 summary を返す fail-open ポリシー（既存 `/v1/context/pack` と同じ流儀）。

### `/v1/context/pack` 側

機能変更なし。テストで以下を assert する:

- 階層 summary（`summary_level=session`）が repo_id 経由で取れる。
- `tokens_saved_vs_raw > 0` が response の `token_budget` に反映されている。
- raw evidence が `omitted[*]` に落ちて `items` に出ない。

## Files touched

- `photon_action_memory/api/server.py`
  — `/v1/summarize` stub を撤去し、本実装に差し替える。
  — `SummarizeRequest` / `SummarizeResponse` を `SidecarModel` で追加。
- `tests/test_sidecar_api.py`
  — M2 stub test を新しい契約に置き換える。
- `tests/test_context_pack.py` または新規 `tests/test_summarize_endpoint.py`
  — 階層 summarize → pack の end-to-end を assert。

## Out of scope

- `chunk_ids` 経由の lookup（chunk store がまだ無いため、本 PR では
  ActionChunk をリクエスト body に直接渡す）。
- `policy` フィールドの実効化。M2 互換のため受理だけ行う。
- 既存 fixtures や Anvil 配信フローへの破壊的変更。

## Safety / regression notes

- prompt-only summary mode は admission controller 側で保証済み — raw
  evidence の流入リスクは新エンドポイントでも上がらない（書き込み専用）。
- `tokens_saved_vs_raw` は既存ユニットテスト
  (`test_context_pack.py::test_token_budget_tokens_saved_vs_raw` 等) で
  網羅されている。本 PR では response surface の追加 assertion を増やすのみ。
- 既存 `/v1/summary/upsert` の挙動は変更しない（後方互換）。
