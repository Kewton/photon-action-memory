# v0.3.0 Develop Connection Test Tasks

作成日: 2026-05-08

## 目的

Anvil `develop` と photon-action-memory `develop` を接続し、まず shadow mode で安全に連携できることを確認する。

対象:

- Anvil: `/Users/maenokota/share/work/github_kewton/Anvil-develop`
- photon-action-memory: `/Users/maenokota/share/work/github_kewton/photon-action-memory`

## 進捗凡例

| 状態 | 意味 |
|---|---|
| 完了 | 既に確認または実施済み |
| 未着手 | これから実施する |
| 注意 | 実施前に整理または判断が必要 |
| 任意 | 接続テスト後に必要に応じて実施 |

## 現在の全体状況

| 項目 | 状態 | メモ |
|---|---|---|
| Anvil photon 関連 PR の develop merge | 完了 | #563-#573 が develop に merge 済み |
| photon-action-memory Anvil 関連 PR の develop merge | 完了 | #74-#81 が develop に merge 済み |
| Anvil local develop | 完了 | `develop...origin/develop` で clean |
| photon-action-memory local develop | 注意 | 現状の develop ブランチで作業中。`origin/develop` へ fast-forward 済み、既存の未コミット変更あり |
| develop 向け open PR | 完了 | Anvil / photon-action-memory とも open PR なし |
| main 取り込み | 未着手 | 今回の develop 接続テスト後に判断 |
| 対応済み Issue close | 未着手 | main 取り込み後に close する想定 |

## 残タスク

### 1. photon-action-memory sidecar 単体 smoke

| ID | タスク | 状態 | 完了条件 |
|---|---|---|---|
| T1-1 | 依存関係確認 | 完了 | 既存環境で `photon_action_memory`, `fastapi`, `uvicorn` を import 可能 |
| T1-2 | sidecar を `127.0.0.1:18765` で起動 | 完了 | `python -m uvicorn photon_action_memory.api.server:app --host 127.0.0.1 --port 18765` が起動 |
| T1-3 | `/health` smoke | 完了 | `GET /health` が `status=ok` を返す |
| T1-4 | `/v1/context/pack` smoke | 完了 | shared raw-log fixture で HTTP 200、raw stdout/stderr が items に入らない |
| T1-5 | `/v1/evaluate` smoke | 完了 | shared shadow fixture で `logged=1` |
| T1-6 | `/v1/summary/upsert` smoke | 完了 | `anvil_action_summary.json` を保存できる |

注意:

- photon-action-memory sidecar では port 3000 を使わない。
- 接続先は `http://127.0.0.1:18765` に統一する。

### 2. Anvil shadow mode 接続

| ID | タスク | 状態 | 完了条件 |
|---|---|---|---|
| T2-1 | Anvil の photon env を shadow mode に設定 | 完了 | 下記 env が設定される |
| T2-2 | Anvil から sidecar へ接続 | 完了 | `/v1/context/pack` が Anvil 実行中に呼ばれる |
| T2-3 | shadow mode の非注入確認 | 完了 | context pack は作るが prompt へ注入しない |
| T2-4 | turn 後 evaluate 確認 | 完了 | `/v1/evaluate` が呼ばれ、`shadow_not_injected` が記録される |

Shadow mode env:

```bash
ANVIL_PHOTON_ENABLED=true
ANVIL_PHOTON_URL=http://127.0.0.1:18765
ANVIL_PHOTON_SHADOW_MODE=true
ANVIL_PHOTON_CANARY=false
ANVIL_PHOTON_TIMEOUT_MS=500
ANVIL_PHOTON_MAX_MEMORY_TOKENS=1200
ANVIL_PHOTON_MAX_EVIDENCE_CHARS=4000
```

### 3. 実行シナリオ

| ID | タスク | 状態 | 完了条件 |
|---|---|---|---|
| T3-1 | 小さな対象 repo または fixture repo を決める | 完了 | `/tmp/anvil-t3-fixture`（`run.sh`で stdout/stderr 生成）を用意 |
| T3-2 | Anvil で 1 turn 実行 | 完了 | Anvil が `./run.sh` を Bash で実行し exit=0 で完了 |
| T3-3 | raw stdout/stderr を伴う操作を含める | 完了 | sidecar に raw_evidence 送付 → admission で 2件 deny 確認 |
| T3-4 | Anvil prompt 非注入を確認 | 完了 | LLM 全メッセージに photon context なし（`raw_tool_tokens_in_prompt == 0`）|

推奨する最小シナリオ:

1. 小さな fixture repo を開く。
2. build/test/search のいずれかで stdout/stderr を発生させる。
3. Anvil が context pack を作る。
4. shadow mode のため prompt には注入しない。
5. turn 後に evaluate を送る。

### 4. 安全性確認

| ID | タスク | 状態 | 完了条件 |
|---|---|---|---|
| T4-1 | raw log 非注入 | 完了 | shadow_mode/canary_gate 両パスで photon 経由の raw 注入なし |
| T4-2 | context pack admission decision 確認 | 完了 | stdout/stderr が deny/omitted として記録される（T3-3 参照） |
| T4-3 | sidecar timeout/fail-open 確認 | 完了 | port 19999 でも Anvil exit=0、WARN のみで turn 継続 |
| T4-4 | canary 無効確認 | 完了 | `ANVIL_PHOTON_CANARY=false` → canary_gate スキップ、LLM 注入なし |

### 5. rollout metrics 確認

| ID | タスク | 状態 | 完了条件 |
|---|---|---|---|
| T5-1 | evaluate records の保存確認 | 完了 | sidecar DB に 4件、全て `adoption_status=shadow_not_injected` |
| T5-2 | rollout metrics 入力の確認 | 完了 | `photon_eval_turns=1`, `raw_tool_tokens_in_prompt=0`, `fail_open_incident_rate=3/8` |
| T5-3 | canary 判定は実行のみ | 完了 | `photon-rollout-check` で条件1/3/4=OK、条件2=NG(要100件)、条件5=ManualRequired → canary 有効化なし |

今回の接続テストでは canary 有効化は範囲外。まず shadow mode の計測が正しく取れることを優先する。

### 6. 結果記録

| ID | タスク | 状態 | 完了条件 |
|---|---|---|---|
| T6-1 | テスト記録ファイルを作成 | 完了 | `workspace/v0.3.0/develop-connection-test-result.md` に Task 1-5 全結果を記録 |
| T6-2 | 実行日時と commit を記録 | 完了 | Anvil `bc34284` / photon-action-memory `f40065e` を記録 |
| T6-3 | sidecar 起動コマンドと env を記録 | 完了 | Task 1 の再現情報を記録 |
| T6-4 | API smoke 結果を記録 | 完了 | `/health`, `/context/pack`, `/evaluate`, `/summary/upsert` の結果を記録 |
| T6-5 | Anvil 実行結果を記録 | 完了 | Tasks 2-5 の実行結果・sequencing 修正・rollout metrics を記録 |
| T6-6 | 失敗/timeout/fail-open の有無を記録 | 完了 | 422 エラー解消・fail-open 3/8 件（うち 1 件は意図的テスト T4-3）を記録 |

## 接続テスト後の後続タスク

| ID | タスク | 状態 | 完了条件 |
|---|---|---|---|
| F1 | 両 repo の develop を main に取り込む | 任意 | develop 接続テストが通った後に main 向け PR を作る |
| F2 | merged issue を close | 任意 | main merge 後、対応済み Issue を close |
| F3 | 古い worktree cleanup | 任意 | merge 済み feature worktree を安全に削除 |
| F4 | canary 実機テスト計画を作る | 任意 | shadow mode が安定してから別タスク化 |

## 現時点の優先順位

1. Anvil shadow mode で sidecar に接続する。
2. raw log 非注入と evaluate log を確認する。
3. 結果を `workspace/v0.3.0/develop-connection-test-result.md` に追記する。
