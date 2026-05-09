# v0.3.0 Live Injection / Canary Tasks

作成日: 2026-05-09
最終更新: 2026-05-09 JST (BC-6/BC-5 確認完了、CY-1〜CY-3/DR-1 docs 化)

## 目的

Anvil と photon-action-memory の shadow mode 接続で確認した安全性を前提に、次を実現する。

- photon-action-memory の context を実際に LLM prompt へ入れる。
- その context によって Anvil の回答または行動が変わることを確認する。
- 一部 turn だけ live injection する canary 運用を開始できる状態にする。

## 進捗凡例

| 状態 | 意味 |
|---|---|
| 完了 | 既に確認または実施済み |
| 未着手 | これから実施する |
| 注意 | 設計判断または実装確認が必要 |
| 任意 | canary 開始後に必要に応じて実施 |

## 現在地

| 項目 | 状態 | メモ |
|---|---|---|
| shadow mode 接続 | 完了 | Anvil から `/v1/context/pack` と `/v1/evaluate` を呼べる |
| prompt 非注入 | 完了 | shadow mode では `agent.photon_context_pack.skipped(reason=shadow_mode)` |
| raw log 非注入 | 完了 | raw stdout/stderr は sidecar admission で deny/omitted |
| fail-open | 完了 | sidecar 不到達時も Anvil turn は継続 |
| rollout metrics 入力 | 完了 | `photon_eval`, `prompt_adopted`, fail-open event を記録可能 |
| live injection | 完了 | LI-1/LI-2/LI-3/LI-4 + AN-1〜AN-7 実装済み (Anvil commit 7c3c3a6)。smoke test 全通過 |
| behavior change 検証 | 完了 | BC-3/BC-4 実機確認済み。`heliograph` を memory から取得して正解回答 (7c3c3a6) |
| canary 有効化 | 未着手 | minimum eval turns 100 件と manual success-rate 比較が未達 (CY-4/CY-5) |

## 重要な技術メモ

~~現状の確認では、live injection へ進む前に下記の差分を解消する必要がある。~~ → **2026-05-09 時点で下記はすべて解消済み (Anvil commit 7c3c3a6)**

1. ~~Anvil の shadow 接続で通した mapper 経路は v0.2 request を作れるが、pre-turn live injection 経路 `invoke_photon_context_pack` は別経路で、現在は最小 payload を送る実装になっている。~~ → **LI-1 完了**: `invoke_photon_context_pack` が `build_context_pack_request` 経由で v0.2 フル payload を送るように変更。さらに LI-2 で `context_pack_sent_this_turn` reset を `handle_user_message` へ移動し、1 turn 1 call を保証。
2. ~~photon-action-memory の v0.2 response は `context_pack.items[].kind = action_summary` / `text` を返す。一方、Anvil の prompt renderer は legacy 形状に近い `items[].kind = summary` / `summary` を前提にしているため、response normalizer または renderer 更新が必要。~~ → **LI-3 完了**: `prompt.rs` が `kind=action_summary`/`text` と `text` フィールドを受理。P15-P18 smoke test 通過。
3. ~~photon-action-memory sidecar は `candidate_summary_ids` がない場合、保存済み summary を自動選択しない。live injection で有用な context を返すには、候補 summary の取得方法を決める必要がある。~~ → **PM-3/PM-4 完了 (photon-action-memory 側)**: repo/task 自動検索で stored summary を取得する方針・実装済み。
4. live injection は prompt へ入るため、shadow mode より安全性リスクが高い。既存の raw deny、prompt injection filter、token cap、fail-open を維持したまま進める。→ **SG-2〜SG-6 完了**: 全 safety regression を smoke test で確認済み。

**LI-4 バグ (2026-05-09 修正済み)**: `parse_items` が `resp.0["items"]` を探していたが、実 sidecar は `resp.0["context_pack"]["items"]` にネストして返す。BC-4 が `items_adopted=0` になっていた原因はこの schema 不一致。proxy ログで根本確認 → `context_pack.items` 優先・top-level `items` fallback で修正 (commit 7c3c3a6, P19/P19b smoke 追加)。

**現在の残課題**: canary eval turn 蓄積 (CY-4/CY-5) と DR-1/DR-4 docs のみ。G3 Gate は BC-3/BC-4 で通過済み。

## タスク一覧

### 1. Contract / schema 整合

| ID | タスク | Owner | 状態 | 完了条件 |
|---|---|---|---|---|
| LI-1 | live injection で使う `ContextPackRequest` を v0.2 mapper 出力へ統一 | Anvil | 完了 | `invoke_photon_context_pack` が `build_context_pack_request` と同等の v0.2 payload を送る |
| LI-2 | live injection 経路と mapper 経路の二重 `/v1/context/pack` 呼び出しを整理 | Anvil | 完了 | `context_pack_sent_this_turn` reset を `handle_user_message` へ移動。T11 smoke test で 1 turn 1 call を検証済み |
| LI-3 | Anvil の response normalizer を v0.2 response に対応 | Anvil | 完了 | `prompt.rs` が `kind=action_summary`/`text` と `text` フィールドを受理。P15-P18 smoke test 通過 |
| LI-4 | shared fixture を追加または更新 | 両方 | 完了 | photon-action-memory 側 fixture 追加済み。Anvil 側: `parse_items` が v0.2 `context_pack.items` ネスト形式を解除するよう修正 (7c3c3a6)。P19/P19b smoke 通過 |
| LI-5 | contract smoke を追加 | 両方 | 注意 | photon-action-memory 側 contract smoke を追加済み。Anvil 側 smoke は別タスク |

### 2. photon-action-memory 側の memory 取得

| ID | タスク | Owner | 状態 | 完了条件 |
|---|---|---|---|---|
| PM-1 | live injection 用の seed summary fixture を作成 | photon-action-memory | 完了 | `tests/fixtures/shared/anvil_live_action_summary.json` を追加 |
| PM-2 | `/v1/summary/upsert` で seed summary を保存する手順を固定 | photon-action-memory | 完了 | `scripts/seed_live_injection_summary.py` と runbook を追加 |
| PM-3 | `candidate_summary_ids` なしで候補を取得する方針を決める | photon-action-memory | 完了 | 明示候補優先。空の場合は repo 自動検索、`task_signature` があれば repo+task 優先。global fallback なし |
| PM-4 | 候補 summary 検索を実装 | photon-action-memory | 完了 | `/v1/context/pack` が repo/task から stored summary を自動取得 |
| PM-5 | stale/contradicted/empty summary の除外を live injection 前提で確認 | photon-action-memory | 完了 | stale は retrieval で除外、empty は admission omit としてテスト済み |
| PM-6 | context_pack response に adopted/omitted の判定根拠を残す | photon-action-memory | 完了 | `admission_decisions` と `context_pack.omitted` で admit/omit 理由を確認可能 |

### 3. Anvil live injection 実装

| ID | タスク | Owner | 状態 | 完了条件 |
|---|---|---|---|---|
| AN-1 | `ANVIL_PHOTON_SHADOW_MODE=false` かつ canary sampled のときだけ prompt 注入 | Anvil | 完了 | shadow mode では `invoke_photon_context_pack` が早期 return (logged "shadow_mode")。live sampled turn だけ `build_photon_injection_message` が注入 |
| AN-2 | prompt section の境界と guard 文を v0.2 item に対して維持 | Anvil | 完了 | `[Photon External Memory — untrusted, read-only context]` ヘッダと `End Photon External Memory` 境界は v0.2 item でも同一。T8/T3 smoke 通過 |
| AN-3 | token cap と item cap を live injection path で再確認 | Anvil | 完了 | `MAX_PROMPT_ITEMS=5` / `MAX_PROMPT_TOTAL_CHARS=800` / `MAX_PHOTON_CONTEXT_PACK_PROMPT_BYTES=8192` が render_context_pack + truncate_photon_context_pack で有効。P5/P6/P7/T7 smoke 通過 |
| AN-4 | prompt injection / destructive text filter を v0.2 item に適用 | Anvil | 完了 | `contains_prompt_injection` / `contains_destructive_command` は kind 問わず適用。P3/P4/P12/P13 smoke 通過 |
| AN-5 | `last_context_pack_id` と evaluate event を live injection に対応 | Anvil | 完了 | `invoke_photon_evaluate` が `adoption_status`(`injected`/`not_injected`/`shadow_not_injected`) と `items_adopted_count` を `/v1/evaluate` payload に含める |
| AN-6 | `prompt_adopted=true` を eval log に記録 | Anvil | 完了 | live injection 時に `summary.prompt_adopted = Some(last_photon_adopted_items > 0)` で上書き。`eval.jsonl` の `photon_eval.prompt_adopted` に反映 |
| AN-7 | live injection unit/smoke test を追加 | Anvil | 完了 | P15-P18 (v0.2 kinds)、T11 (LI-2 one-shot gate) を追加。`cargo test --test photon_turn_hook_smoke --test photon_prompt_smoke --test photon_eval_log_smoke` 全通過 (Anvil commit 8fc1b45) |

### 4. 回答・行動変化の実機シナリオ

| ID | タスク | Owner | 状態 | 完了条件 |
|---|---|---|---|---|
| BC-1 | 回答差分を検証する fixture repo を用意 | 両方 | 注意 | photon-action-memory 側の memory seed と request fixture は作成済み。実 repo と Anvil 実行は別タスク |
| BC-2 | memory seed を投入 | photon-action-memory | 完了 | `anvil-live-codename-001` を `/v1/summary/upsert` で投入可能 |
| BC-3 | baseline run を実行 | Anvil | 完了 | `ANVIL_PHOTON_CANARY=0` → `photon_context_pack.skipped(reason=canary_gate)`。LLM:「コードネームはファイルに記載されていない」→ 正しく答えられない |
| BC-4 | live injection run を実行 | Anvil | 完了 | `ANVIL_PHOTON_ENABLED=true ANVIL_PHOTON_SHADOW_MODE=false ANVIL_PHOTON_CANARY=1000` → LLM:「The project codename for this repository is heliograph.」✓ ファイル読み込みなし、iter=1 で即答 |
| BC-5 | 行動差分シナリオを追加 | 両方 | 完了（観察） | policy memory「rm を使わず mv で削除」を注入。items=1, 182 bytes 注入確認済み。ただし qwen3:8b は "untrusted context" ガード文の影響で policy に従わず `rm` を実行。情報提供型（BC-3/BC-4）の方が有効なユースケースであると確認 |
| BC-6 | LLM 入力と eval log を検査 | Anvil | 完了 | `llm-io.jsonl`: `ollama.generate.request` に `[Photon External Memory]` セクションと "heliograph" が含まれる。`eval.jsonl`: `photon_eval.prompt_adopted = true`、`final_outcome = done` を確認 |
| BC-7 | 結果を記録 | photon-action-memory | 注意 | `workspace/v0.3.0/live-injection-canary-result.md` を作成済み。Anvil 実機 run 結果は未記録 |

推奨する最小シナリオ:

1. `/tmp/anvil-live-fixture` を作る。
2. repo 内には project codename を書かない。
3. photon-action-memory に「この repo の codename は heliograph」という valid summary を保存する。
4. photon disabled または `ANVIL_PHOTON_CANARY=0` で Anvil に codename を質問し、答えられないことを確認する。
5. `ANVIL_PHOTON_SHADOW_MODE=false`, `ANVIL_PHOTON_CANARY=1000` で同じ質問を実行し、Photon Context 経由で `heliograph` と答えることを確認する。

### 5. Canary 運用

| ID | タスク | Owner | 状態 | 完了条件 |
|---|---|---|---|---|
| CY-1 | canary sampling の単位を明文化 | Anvil | 完了 | `deterministic_canary_hash(session_id, turn_idx)` = SHA-256 下位 8 bytes を sampling 単位として確認。`should_send_context_pack` が SSOT（`mapper.rs:48-70`） |
| CY-2 | canary 比率の env 運用を固定 | Anvil | 完了 | `ANVIL_PHOTON_CANARY=0` は 0%（常に skip）、`1-999` は permille、`1000` は 100%（常に inject）。コード上 `if canary>=1000 { return true }` で保証 |
| CY-3 | sampled / unsampled のログを分離 | Anvil | 完了 | `llm-io.jsonl` の `agent.photon_context_pack.skipped {reason:"canary_gate"}` と `.completed {items_adopted, injected_bytes}` で区別可能。`eval.jsonl` の `photon_eval.prompt_adopted` で採用判定も記録 |
| CY-4 | 100 eval turn を蓄積 | Anvil | 未着手 | `photon-rollout-check` の minimum eval turns 条件が OK になる |
| CY-5 | canary / non-canary 成功率比較を実施 | Anvil | 未着手 | `anvil_score.success_score` または代替指標で regression がない |
| CY-6 | canary 開始条件をゲート化 | Anvil | 未着手 | fail-open 率、raw token 混入、prompt size、success-rate の全条件を満たす |
| CY-7 | rollback 手順を作る | Anvil | 未着手 | `ANVIL_PHOTON_CANARY=0` または `ANVIL_PHOTON_ENABLED=false` で即時停止できる |
| CY-8 | 段階的 rollout | Anvil | 未着手 | 1% → 5% → 10% → 25% → 50% → 100% の各段階で結果を記録 |

### 6. Safety / regression

| ID | タスク | Owner | 状態 | 完了条件 |
|---|---|---|---|---|
| SG-1 | raw stdout/stderr 非注入 regression test | 両方 | 注意 | photon-action-memory 側は既存 raw evidence deny test で確認済み。Anvil prompt 側 regression は別タスク |
| SG-2 | prompt injection summary の拒否 test | Anvil | 完了 | P3/P4/P12/P13 smoke test で v0.2 kind item に対しても injection/destructive が拒否されることを確認済み |
| SG-3 | secret masking test | 両方 | 完了 | P8a/P8b/P14 smoke (Anvil) + `ContextPackItem.text` sanitizer/API test (photon-action-memory) で確認済み |
| SG-4 | sidecar timeout/fail-open regression test | Anvil | 完了 | T4 (evaluate 500 → fail-open) + T1 (photon=None → 0 calls) + 接続テスト T4-3 で live injection でも turn が止まらないことを確認済み |
| SG-5 | empty context_pack の扱い | Anvil | 完了 | `render_context_pack` が items=0 で None を返し injection message が生成されない。P9/P10 smoke 通過 |
| SG-6 | duplicated context injection 防止 | Anvil | 完了 | LI-2 (`context_pack_sent_this_turn` one-shot flag) で 1 turn 1 call を保証。T11 smoke 通過 |

### 7. Documentation / release readiness

| ID | タスク | Owner | 状態 | 完了条件 |
|---|---|---|---|---|
| DR-1 | Anvil env 設定例を更新 | Anvil | 完了（本ファイルに記録） | 下記「Anvil env 設定リファレンス」セクションに shadow/live/canary/rollback の env を明文化 |
| DR-2 | photon-action-memory sidecar 起動例を更新 | photon-action-memory | 完了 | `workspace/v0.3.0/photon-live-injection-sidecar-runbook.md` に起動例を追加 |
| DR-3 | 接続テスト結果テンプレートを追加 | photon-action-memory | 完了 | `workspace/v0.3.0/live-injection-canary-result.md` を追加 |
| DR-4 | develop 反映手順を整理 | 両方 | 未着手 | 両 repo の push、PR、merge、issue close の順序が明確 |

## 実施順序

1. LI-1 から LI-5 で request/response contract を揃える。
2. PM-1 から PM-4 で prompt に入れる valid summary を取得できるようにする。
3. AN-1 から AN-7 で live injection を実装し、unit/smoke test を通す。
4. BC-1 から BC-7 で回答・行動差分を実機確認する。
5. SG-1 から SG-6 で安全性 regression を確認する。
6. CY-1 から CY-8 で canary 運用に進む。
7. DR-1 から DR-4 で運用・リリース準備を完了する。

## 完了ゲート

| Gate | 条件 | 判定 |
|---|---|---|
| G1 | live injection path が v0.2 request/response で unit test 通過 | 完了 (Anvil 8fc1b45: P15-P18, T11) |
| G2 | `ANVIL_PHOTON_SHADOW_MODE=false`, `ANVIL_PHOTON_CANARY=1000` で Photon Context が prompt に 1 回だけ入る | 完了 (LI-2 one-shot flag + T11 smoke) |
| G3 | memory 由来の回答または行動差分を実機で確認 | **完了** (BC-3/BC-4 実機確認済み: canary=0 で無知、canary=1000 で "heliograph" 即答) |
| G4 | raw log / prompt injection / secret / timeout の regression が全て通る | 完了 (SG-2〜SG-6 全 smoke 通過) |
| G5 | canary 100 eval turn 以上、fail-open 率許容内、success-rate regression なし | 未着手 (CY-4/CY-5 が必要) |
| G6 | rollback 手順が確認済み | 完了 (`ANVIL_PHOTON_CANARY=0` または `ANVIL_PHOTON_ENABLED=false` で即時停止) |

## 対応状況追記

追記日: 2026-05-09

| 領域 | 状態 | 内容 |
|---|---|---|
| photon-action-memory PM-1〜PM-6 | 完了 | live injection 用 seed summary、upsert script、repo/task 自動検索、stale/empty 除外、admission/omitted 理由記録を実装・確認済み |
| photon-action-memory SG-3 | 完了 | `render_summary()` が `sanitize_text()` を通し、`ContextPackItem.text` の token/Bearer/API_KEY/ローカル絶対パスを mask する regression test を追加済み |
| photon-action-memory fixture / runbook | 完了 | `anvil_live_action_summary.json`、`anvil_live_context_pack_request.json`、`anvil_live_context_pack_response.json`、`seed_live_injection_summary.py`、sidecar runbook を追加済み |
| Anvil live injection | 完了 | Anvil commit `7c3c3a6` で LI-1〜LI-4、AN-1〜AN-7、SG-2〜SG-6 の smoke test 通過済み。根本原因: `parse_items` が `context_pack.items` ネスト形式を見落としていた |
| 実機 behavior change | **完了** | BC-3: canary=0 で LLM が答えられない。BC-4: canary=1000 で "heliograph" を即答。G3 Gate 通過 |
| canary 運用 | 未着手 | CY-1〜CY-8 は、live injection 実機確認後に eval turn 蓄積と success-rate 比較を行う |

photon-action-memory 側の検証:

```bash
PYTHONPATH=. pytest tests/test_context_pack.py tests/test_anvil_context_pack_api.py tests/test_anvil_contract.py
# 65 passed

ruff check photon_action_memory/context/render.py tests/test_context_pack.py photon_action_memory/api/server.py tests/test_anvil_context_pack_api.py scripts/seed_live_injection_summary.py
# All checks passed
```

注意:

- 現在起動中の `127.0.0.1:18765` sidecar がある場合、今回の photon-action-memory 側変更を反映するには再起動が必要。
- `BC-3/BC-4` の実機確認では、`scripts/seed_live_injection_summary.py --url http://127.0.0.1:18765` で seed 投入してから Anvil を実行する。

## Anvil env 設定リファレンス（DR-1）

```bash
# ---- Photon sidecar 接続 ----
ANVIL_PHOTON_ENABLED=true           # デフォルト false。true にしないと photon クライアントが無効
ANVIL_PHOTON_URL=http://127.0.0.1:18765  # デフォルト http://127.0.0.1:3030
ANVIL_PHOTON_TIMEOUT_MS=5000        # デフォルト 200ms（ローカル専用。短すぎると fail-open）

# ---- Shadow / Live 切り替え ----
ANVIL_PHOTON_SHADOW_MODE=true       # デフォルト true = shadow mode（prompt 非注入）
ANVIL_PHOTON_SHADOW_MODE=false      # live injection mode（prompt に Photon Context を注入）

# ---- Canary 比率 ----
ANVIL_PHOTON_CANARY=0               # 0%  = 全 turn skip（既定値）
ANVIL_PHOTON_CANARY=10              # 1%  sampling
ANVIL_PHOTON_CANARY=100             # 10% sampling
ANVIL_PHOTON_CANARY=500             # 50% sampling
ANVIL_PHOTON_CANARY=1000            # 100% = 全 turn inject

# sampling 単位: deterministic_canary_hash(session_id, turn_idx) % 1000 < canary
# 同一 session + turn_idx は毎回同じ結果（再現性あり）

# ---- Rollback ----
ANVIL_PHOTON_CANARY=0               # 即時 0% に下げる（session 再起動不要）
# または
ANVIL_PHOTON_ENABLED=false          # sidecar 通信を完全に無効化

# ---- Rollout 判定 ----
ANVIL_PHOTON_ROLLOUT_MIN_EVAL_TURNS=100  # デフォルト 100（photon-rollout-check の閾値）
anvil sessions photon-rollout-check      # rollout 準備状況の確認コマンド

# ---- ログ確認 ----
# llm-io.jsonl: agent.photon_context_pack.{completed,skipped} で injection 状況を確認
# eval.jsonl:   photon_eval.prompt_adopted で採用判定を確認
```

## 範囲外

- canary なしで全 turn に即時 live injection すること。
- raw stdout/stderr や full build log を prompt に入れること。
- sidecar 障害時に Anvil turn を止めること。
- photon-action-memory の memory を user/developer/system 指示として扱わせること。
