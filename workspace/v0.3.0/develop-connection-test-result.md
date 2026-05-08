# v0.3.0 Develop Connection Test Result

作成日: 2026-05-08
最終更新: 2026-05-09 JST

## 対象

| 項目 | 値 |
|---|---|
| photon-action-memory | `/Users/maenokota/share/work/github_kewton/photon-action-memory` |
| photon-action-memory branch | `develop` |
| photon-action-memory commit | `f40065e` |
| Anvil | `/Users/maenokota/share/work/github_kewton/Anvil-develop` |
| Anvil branch | `develop` |
| Anvil commit | `bc34284` (photon schema v0.2 + sequencing fix) |

## Task 1: photon-action-memory sidecar 単体 smoke

| ID | 結果 | 確認内容 |
|---|---|---|
| T1-1 | 完了 | `photon_action_memory`, `fastapi`, `uvicorn` を既存環境で import 可能 |
| T1-2 | 完了 | sidecar を `127.0.0.1:18765` で起動 |
| T1-3 | 完了 | `GET /health` が HTTP 200 / `status=ok` |
| T1-4 | 完了 | `/v1/context/pack` が HTTP 200、raw stdout/stderr は items に非混入 |
| T1-5 | 完了 | `/v1/evaluate` が HTTP 200、`logged=1` |
| T1-6 | 完了 | `/v1/summary/upsert` が HTTP 200、summary を保存 |

## 実行条件

sidecar 起動コマンド:

```bash
PHOTON_ACTION_MEMORY_DB=/tmp/photon-action-memory-v030-task1-events.sqlite \
PHOTON_ACTION_MEMORY_SUMMARY_DB=/tmp/photon-action-memory-v030-task1-summaries.sqlite \
python -m uvicorn photon_action_memory.api.server:app --host 127.0.0.1 --port 18765
```

使用 fixture:

- `tests/fixtures/shared/context_pack_request_with_raw_log.json`
- `tests/fixtures/shared/evaluate_shadow_not_injected.json`
- `tests/fixtures/photon/anvil_action_summary.json`

## API smoke 結果

```json
{
  "health": {
    "http_status": 200,
    "status": "ok",
    "schema_version": "action-memory.v1"
  },
  "context_pack": {
    "http_status": 200,
    "sidecar_status": "ok",
    "item_count": 0,
    "raw_in_items": false,
    "admission_decision_count": 2,
    "admission_decisions": [
      "deny",
      "deny"
    ]
  },
  "evaluate": {
    "http_status": 200,
    "status": "ok",
    "logged": 1
  },
  "summary_upsert": {
    "http_status": 200,
    "status": "stored",
    "summary_id": "anvil-sum-photon-001"
  }
}
```

## 補足

- Task 1 では port 3000 を使用していない。
- smoke 後、sidecar は停止済み。
- 実行前に photon-action-memory `develop` を `origin/develop` へ fast-forward した。
- fast-forward のため、未追跡だった `workspace/anvil/summary.md` は `stash@{0}` (`pre-v0.3.0-task1-workspace-anvil-summary`) に退避した。
- 既存の未コミット変更として `scripts/codex_orchestrate.py` と `tests/test_codex_orchestrate.py` が残っている。
- Anvil 実行は Task 1 の範囲外。Task 2 以降で shadow mode 接続を確認する。

---

## Task 2: Anvil shadow mode 接続

| ID | 結果 | 確認内容 |
|---|---|---|
| T2-1 | 完了 | shadow mode env を設定（下記参照） |
| T2-2 | 完了 | `/v1/context/pack` が Anvil 実行中に呼ばれる（mapper path） |
| T2-3 | 完了 | shadow mode のため prompt への注入はスキップ（`agent.photon_context_pack.skipped reason=shadow_mode` を確認） |
| T2-4 | 完了 | `/v1/evaluate` が成功し、`shadow_not_injected` が sidecar に記録される |

### 実行条件

sidecar 起動コマンド（Task 1 の sidecar をそのまま継続使用）:

```bash
PHOTON_ACTION_MEMORY_DB=/tmp/photon-action-memory-v030-sidecar-events.sqlite \
PHOTON_ACTION_MEMORY_SUMMARY_DB=/tmp/photon-action-memory-v030-sidecar-summaries.sqlite \
python -m uvicorn photon_action_memory.api.server:app --host 127.0.0.1 --port 18765
```

Anvil 実行 env:

```bash
ANVIL_PHOTON_ENABLED=true
ANVIL_PHOTON_URL=http://127.0.0.1:18765
ANVIL_PHOTON_SHADOW_MODE=true
ANVIL_PHOTON_CANARY=false   # 0 として扱われる（shadow mode では不要）
ANVIL_PHOTON_TIMEOUT_MS=500
```

Anvil 実行コマンド:

```bash
./target/release/anvil --model qwen3.5:2b -y --oneshot -p "Run ls -la and summarize the output."
```

### スキーマ修正内容

接続テスト中に sidecar と Anvil の JSON スキーマ不一致（HTTP 422）を発見し修正した。

#### 修正箇所 1: `src/photon/mapper.rs`

`PHOTON_CONTEXT_PACK_SCHEMA_VERSION` を `u8 = 1` から `&str = "action-memory.v0.2"` に変更。
`build_context_pack_request` の出力を sidecar が要求するネスト構造（`agent`/`repo`/`task`/`working_memory` オブジェクト＋`request_id`）に変更。

#### 修正箇所 2: `src/agent/loop_run/turn.rs`（`invoke_photon_evaluate`）

evaluate request に `schema_version`/`request_id`/`agent` オブジェクト/`context_pack_event` を追加。
`last_context_pack_id` が None の場合は `context_pack_event: null` を送るよう修正（sidecar が `context_pack_request_id: str` を必須とするため）。

#### 修正箇所 3: `src/agent/loop_run/turn.rs`（path (b) — mapper path）

`build_request_messages` 内の mapper 呼び出し経路で、ビルドしたリクエストの `request_id` を `self.last_context_pack_id` にセット。shadow mode では `invoke_photon_context_pack` がスキップされるため、この経路でのみ context_pack_id を取得できる。

#### 修正箇所 4: `tests/photon_mapper_smoke.rs`

スキーマ変更に合わせて 20 件のテストを更新（T1/T2/T4/T5/T11/T13/T15）。

### 確認結果

```
llm-io.jsonl (最新 turn):
  agent.photon_context_pack.skipped: reason=shadow_mode       ← T2-3 確認
  agent.photon_evaluate.completed: failed=false               ← T2-4 確認

sidecar events DB (events テーブル):
  id=1: event_type=context_pack_eval
        adoption_status=shadow_not_injected
        context_pack_request_id=019e06b2-...  ← Anvil が生成した UUID  ← T2-4 確認
```

stderr に 422 エラーなし（`WARN photon POST ... failed` が出なくなった）← T2-2 確認

---

## Task 3: 実行シナリオ

| ID | 結果 | 確認内容 |
|---|---|---|
| T3-1 | 完了 | fixture repo `/tmp/anvil-t3-fixture`（`run.sh` で stdout/stderr を生成）を用意 |
| T3-2 | 完了 | Anvil が `./run.sh` を Bash ツールで実行し turn 完了（exit=0） |
| T3-3 | 完了 | sidecar に raw_evidence(stdout/stderr)を送り、admission で 2件 deny を確認 |
| T3-4 | 完了 | LLM メッセージに photon context 注入なし（`raw_tool_tokens_in_prompt == 0`） |

### 実行条件

fixture repo:

```bash
mkdir -p /tmp/anvil-t3-fixture
# run.sh: stdout/stderr を生成するシェルスクリプト
git init /tmp/anvil-t3-fixture
```

Anvil 実行コマンド（fixture repo のディレクトリで実行）:

```bash
cd /tmp/anvil-t3-fixture
ANVIL_PHOTON_ENABLED=true \
ANVIL_PHOTON_URL=http://127.0.0.1:18765 \
ANVIL_PHOTON_SHADOW_MODE=true \
ANVIL_PHOTON_CANARY=false \
ANVIL_PHOTON_TIMEOUT_MS=500 \
anvil --model qwen3.5:2b -y --oneshot \
  -p "Run ./run.sh and report what it outputs to stdout and stderr."
```

### T3-3: raw evidence admission deny 確認

sidecar への直接 API テスト:

```bash
curl -X POST http://127.0.0.1:18765/v1/context/pack \
  -H "Content-Type: application/json" \
  -d '{
    "schema_version": "action-memory.v0.2",
    "request_id": "t33-admission-test-001",
    "agent": {"name": "anvil", "version": "0.6.0"},
    "repo": {"root": "/tmp/anvil-t3-fixture", "name": "anvil-t3-fixture"},
    "task": {"user_request": "Run ./run.sh", "mode": "act"},
    "working_memory": {"active_task": "Run ./run.sh", "touched_files": []},
    "raw_evidence": [
      {"item_id": "bash-stdout-001", "kind": "stdout", "content": "..."},
      {"item_id": "bash-stderr-001", "kind": "stderr", "content": "..."}
    ]
  }'
```

sidecar 応答:

```json
{
  "sidecar_status": "ok",
  "context_pack": {
    "items": [],
    "omitted": [
      {"kind": "stdout", "id": "bash-stdout-001", "reason": "raw tool log default deny policy: kind 'stdout' is always denied"},
      {"kind": "stderr", "id": "bash-stderr-001", "reason": "raw tool log default deny policy: kind 'stderr' is always denied"}
    ]
  },
  "admission_decisions": [
    {"item_id": "bash-stdout-001", "item_kind": "raw_tool_log", "decision": "deny", "reason": "raw tool log default deny policy: kind 'stdout' is always denied"},
    {"item_id": "bash-stderr-001", "item_kind": "raw_tool_log", "decision": "deny", "reason": "raw tool log default deny policy: kind 'stderr' is always denied"}
  ]
}
```

### T3-4: prompt 非注入確認

```
llm-io.jsonl (session=019e0753):
  agent.photon_context_pack.skipped: reason=shadow_mode       ← shadow mode により注入スキップ
  agent.photon_evaluate.completed: failed=false               ← evaluate 成功

LLM メッセージ (ollama.generate.request):
  7 messages, no photon injection  ← photon context セクションなし
  9 messages, no photon injection  ← 2回目の LLM 呼び出しも注入なし

sidecar events DB:
  id=3: adoption_status=shadow_not_injected, session=019e0753-...
```

### 設計上の補足

Anvil の mapper は raw tool output を context_pack リクエストに含めない（`recent_tool_summary` は name + args_summary のみ）。  
そのため Anvil 側から送る context_pack リクエストには raw_evidence がなく admission decision は 0 件となる。  
T3-3 で確認した raw evidence 拒否ポリシーは、仮に raw_evidence が送られた場合の sidecar 側の防御として機能する。

---

## Task 4: 安全性確認

| ID | 結果 | 確認内容 |
|---|---|---|
| T4-1 | 完了 | raw stdout/stderr が photon 経由で prompt に入らない（shadow/canary_gate 両パスで確認） |
| T4-2 | 完了 | raw evidence は sidecar admission で deny/omitted（T3-3 結果を参照） |
| T4-3 | 完了 | sidecar 不到達時も Anvil は exit=0 で継続（fail-open WARN のみ） |
| T4-4 | 完了 | `ANVIL_PHOTON_CANARY=false` (=0) で live injection なし（canary_gate スキップ） |

### T4-1: raw log 非注入確認

2つのパスで raw stdout/stderr が prompt に入らないことを確認した。

| パス | 設定 | llm-io.jsonl イベント | LLM への注入 |
|---|---|---|---|
| shadow mode | `SHADOW_MODE=true`, `CANARY=false` | `photon_context_pack.skipped(shadow_mode)` | なし（T3-4 確認済） |
| canary=0 | `SHADOW_MODE=false`, `CANARY=false` | `photon_context_pack.skipped(canary_gate)` | なし（T4-4 確認済） |

いずれのパスでも `photon_context_pack_response = None` となり、`photon_context_pack_injection_message` が None を返すため LLM には photon context セクションが存在しない。

### T4-2: context pack admission decision 確認

T3-3 の結果（再掲）:

- `stdout` / `stderr` / `build_log` / `raw_output` 等の kind は `RAW_DENIED_KINDS` に一致し無条件 deny
- sidecar 応答: `items=[]`, `omitted=[{kind:stdout, reason:...deny}, {kind:stderr, reason:...deny}]`
- `admission_decisions=[{decision:deny}, {decision:deny}]`
- policy: `raw_tool_log_default_deny`

### T4-3: sidecar timeout/fail-open 確認

設定: `ANVIL_PHOTON_URL=http://127.0.0.1:19999`（存在しないポート）、`ANVIL_PHOTON_TIMEOUT_MS=200`

結果:

```
exit=0  ← Anvil は正常終了（turn が止まらない）

stderr:
  WARN photon POST /v1/context/pack failed (fail-open): error sending request for url (http://127.0.0.1:19999/v1/context/pack)
  WARN photon POST /v1/evaluate failed (fail-open): error sending request for url (http://127.0.0.1:19999/v1/evaluate)

llm-io.jsonl:
  agent.photon_context_pack.skipped: reason=shadow_mode   ← path(a) は shadow_mode でスキップ
  agent.photon_evaluate.completed: failed=true            ← 接続失敗、fail-open で継続

Bash tool: ./run.sh または echo hello を実行し出力を報告
```

Anvil の fail-open 実装: `PhotonClient::send_failopen` がエラーを `tracing::warn!` に記録して `None` を返す。sidecar が不在でも LLM turn は正常に進行する。

### T4-4: canary 無効確認

設定: `ANVIL_PHOTON_SHADOW_MODE=false`, `ANVIL_PHOTON_CANARY=false`（→ 0 として扱われる）

結果:

```
exit=0

llm-io.jsonl:
  agent.photon_context_pack.skipped: reason=canary_gate   ← canary=0 → 送信しない
  agent.photon_evaluate.completed: failed=false            ← evaluate は成功（context_pack_event=null）

LLM メッセージ: 14/16 messages, photon_injection=False  ← 注入なし

sidecar events DB: T4-4 の eval record は logged=0 のため DB に行なし
```

`should_send_context_pack(canary=0, shadow=false)` は false を返すため context_pack の HTTP 呼び出しが一切発生しない。evaluate は呼ばれるが `context_pack_event=null` なので sidecar は `logged=0` を返す。

---

## Task 5: rollout metrics 確認

| ID | 結果 | 確認内容 |
|---|---|---|
| T5-1 | 完了 | sidecar DB に 4件、全て `adoption_status=shadow_not_injected` |
| T5-2 | 完了 | `photon_eval_turns=1`, `raw_tool_tokens_in_prompt=0`, `fail_open_incident_rate=3/8` |
| T5-3 | 完了 | `photon-rollout-check` 実行完了、canary 有効化なし |

### バグ発見と修正: `photon_eval` sequencing

**発見**: `eval.jsonl` の `photon_eval` フィールドが常に `null` になっていた。

**根本原因**: `build_eval_record` は `run_actor_loop` の末尾で呼ばれるが、`invoke_photon_evaluate` は `run_turn` で `run_actor_loop` の **後** に呼ばれていた。そのため `last_photon_eval_summary` が常に `None` のまま `build_eval_record` に到達していた。

**修正箇所**: `src/agent/loop_run/turn.rs`

- `run_turn` から photon evaluate hook（`self.photon_context_pack_response = None` + `invoke_photon_evaluate()`）を削除。
- `run_actor_loop` の末尾、`maybe_extract_anti_pattern()` の直後 / `build_eval_record` ブロックの直前に移動。
- Plan mode の skip ログも同じ位置に移動。

**修正後の確認**:

```
eval.jsonl (session=019e0753, record 4):
  photon_eval: {
    "context_pack_id": "019e0811-7829-7380-8325-4cdf2d3c1ed5",
    "admission_decision": null,
    ...
  }
```

`cargo test --test photon_turn_hook_smoke`: 11 passed  
`cargo test --test photon_rollout_policy_smoke`: 12 passed

### T5-1: evaluate records の保存確認

sidecar DB (`/tmp/photon-action-memory-v030-sidecar-events.sqlite`):

```
total records: 4
id=1: session=019de1cb adoption_status=shadow_not_injected (Task 2 test run)
id=2: session=019de1cb adoption_status=shadow_not_injected (Task 2 verify test)
id=3: session=019e0753 adoption_status=shadow_not_injected (Task 3/4 test run)
id=4: session=019e0753 adoption_status=shadow_not_injected (Task 5 fix verification run)
```

全件 `adoption_status=shadow_not_injected` ← T5-1 確認 ✓

### T5-2: rollout metrics 入力の確認

| メトリクス | 値 | 取得方法 |
|---|---|---|
| `photon_eval_turns` | 1（接続テスト 1 run 分） | `photon-rollout-check` / eval.jsonl スキャン |
| `raw_tool_tokens_in_prompt` | 0 | T3-4/T4-1 で LLM 全メッセージに photon injection なしを確認 |
| `fail_open_incident_rate` | 3/8 = 37.5% | llm-io.jsonl の `photon_evaluate.completed(failed=true)` 件数 |

fail-open 3 件の内訳:
- 1 件: T4-3 の意図的なポート変更テスト (`http://127.0.0.1:19999`)
- 2 件: スキーマ修正前の 422 エラー（開発中の一時的な失敗）

正常運用での fail-open 率は 0% となる見込み。

メトリクス取得メカニズム:
- `photon_eval_turns`: eval.jsonl の `photon_eval != null` レコード数（sequencing 修正後に正常動作）
- `raw_tool_tokens_in_prompt`: eval.jsonl の `photon_eval.prompt_adopted` フィールドで追跡可能（shadow mode では常に false）
- `fail_open_incident_rate`: llm-io.jsonl の `agent.photon_evaluate.completed(failed=true)` イベントから集計

### T5-3: canary 判定確認

`./target/release/anvil sessions photon-rollout-check` の出力（修正後）:

```
[OK] Condition 1: sidecar fail-open
    note: already implemented (Issue #554)
[NG] Condition 2: minimum eval turns
    reason: found 1 photon_eval turns, need 100
[OK] Condition 3: unsafe context filter
    note: already implemented (Issue #557)
[OK] Condition 4: prompt size cap
    note: already implemented (Issue #557)
[ManualRequired] Condition 5: task success rate
    manual: compare canary/non-canary anvil_score.success_score externally
    note: photon_canary is logged for external analysis

Rollout BLOCKED: manual verification required before canary
```

- 条件1/3/4 は実装済みで OK。
- 条件2 はこの接続テストでは 1 turn のみ。本番 100 turn 蓄積後に OK になる。
- 条件5 は canary vs 非 canary の成功率比較が必要で ManualRequired → canary 自動有効化は起きない。
- `ANVIL_PHOTON_CANARY=0` 設定のため canary は無効（T4-4 確認済み）。
