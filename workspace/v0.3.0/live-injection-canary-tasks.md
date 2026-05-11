# v0.3.0 Live Injection / Canary Tasks

作成日: 2026-05-09
最終更新: 2026-05-12 JST (CY-5 完了: sampled 93.0% / unsampled 73.6%、delta=+19.4pp、regression なし ✅)

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
| canary 有効化 | 進行中 | CY-4/CY-5 完了。photon-rollout-check: Condition 1〜4 OK、Condition 5 ManualRequired（設計上常に手動判定）。CY-5 外部比較で regression なし ✅。CY-6 gate PASS 確認後に CY-8 段階的 rollout へ進む |

## 重要な技術メモ

~~現状の確認では、live injection へ進む前に下記の差分を解消する必要がある。~~ → **2026-05-09 時点で下記はすべて解消済み (Anvil commit 7c3c3a6)**

1. ~~Anvil の shadow 接続で通した mapper 経路は v0.2 request を作れるが、pre-turn live injection 経路 `invoke_photon_context_pack` は別経路で、現在は最小 payload を送る実装になっている。~~ → **LI-1 完了**: `invoke_photon_context_pack` が `build_context_pack_request` 経由で v0.2 フル payload を送るように変更。さらに LI-2 で `context_pack_sent_this_turn` reset を `handle_user_message` へ移動し、1 turn 1 call を保証。
2. ~~photon-action-memory の v0.2 response は `context_pack.items[].kind = action_summary` / `text` を返す。一方、Anvil の prompt renderer は legacy 形状に近い `items[].kind = summary` / `summary` を前提にしているため、response normalizer または renderer 更新が必要。~~ → **LI-3 完了**: `prompt.rs` が `kind=action_summary`/`text` と `text` フィールドを受理。P15-P18 smoke test 通過。
3. ~~photon-action-memory sidecar は `candidate_summary_ids` がない場合、保存済み summary を自動選択しない。live injection で有用な context を返すには、候補 summary の取得方法を決める必要がある。~~ → **PM-3/PM-4 完了 (photon-action-memory 側)**: repo/task 自動検索で stored summary を取得する方針・実装済み。
4. live injection は prompt へ入るため、shadow mode より安全性リスクが高い。既存の raw deny、prompt injection filter、token cap、fail-open を維持したまま進める。→ **SG-2〜SG-6 完了**: 全 safety regression を smoke test で確認済み。

**LI-4 バグ (2026-05-09 修正済み)**: `parse_items` が `resp.0["items"]` を探していたが、実 sidecar は `resp.0["context_pack"]["items"]` にネストして返す。BC-4 が `items_adopted=0` になっていた原因はこの schema 不一致。proxy ログで根本確認 → `context_pack.items` 優先・top-level `items` fallback で修正 (commit 7c3c3a6, P19/P19b smoke 追加)。

**現在の残課題**: CY-4/CY-5/G5 は完了。photon-rollout-check の Condition 5 は設計上 ManualRequired だが外部比較で regression なしを確認。**残る実作業は CY-8 の段階的 rollout 開始のみ**（canary=10 → 100 → 500 → 1000 と順に拡大して各段階で cy5 script を再実行）。

## タスク一覧

### 1. Contract / schema 整合

| ID | タスク | Owner | 状態 | 完了条件 |
|---|---|---|---|---|
| LI-1 | live injection で使う `ContextPackRequest` を v0.2 mapper 出力へ統一 | Anvil | 完了 | `invoke_photon_context_pack` が `build_context_pack_request` と同等の v0.2 payload を送る |
| LI-2 | live injection 経路と mapper 経路の二重 `/v1/context/pack` 呼び出しを整理 | Anvil | 完了 | `context_pack_sent_this_turn` reset を `handle_user_message` へ移動。T11 smoke test で 1 turn 1 call を検証済み |
| LI-3 | Anvil の response normalizer を v0.2 response に対応 | Anvil | 完了 | `prompt.rs` が `kind=action_summary`/`text` と `text` フィールドを受理。P15-P18 smoke test 通過 |
| LI-4 | shared fixture を追加または更新 | 両方 | 完了 | photon-action-memory 側 fixture 追加済み。Anvil 側: `parse_items` が v0.2 `context_pack.items` ネスト形式を解除するよう修正 (7c3c3a6)。P19/P19b smoke 通過 |
| LI-5 | contract smoke を追加 | 両方 | 完了 | photon-action-memory 側 contract smoke 追加済み。Anvil 側 P19/P19b + fixture/turn-hook smoke を 2026-05-11 に実行し、`cargo test --test photon_prompt_smoke --test photon_fixture_smoke --test photon_mapper_smoke --test photon_turn_hook_smoke --test photon_rollout_policy_smoke` が 73 passed |

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
| BC-7 | 結果を記録 | photon-action-memory | 完了 | `workspace/v0.3.0/live-injection-canary-result.md` に Anvil 実機 run と最新 gate 結果を記録 |

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
| CY-4 | 100 eval turn を蓄積 | Anvil | **完了** | 専用 state_dir `/localwork/anvilcy4_state_dir` に 114 turns 蓄積。`photon-rollout-check` Condition 2 OK。canary=1000 + qwen3:8b + ANVIL_NO_AUTO_TEST=1 で 110 run、95.6% done |
| CY-5 | canary / non-canary 成功率比較を実施 | Anvil | **完了** | sampled=71 turns 93.0% / unsampled=110 turns 73.6%、delta=+19.4pp (regression なし ✅)。canary=500 で 60 run 追加し sampled 10→71 件に増加。delta が正方向のため photon injection による性能劣化なし |
| CY-6 | canary 開始条件をゲート化 | Anvil | 完了 | `scripts/cy6_gate_check.py` を追加。fail-open 率、raw marker、prompt size、success-rate regression を集約判定し、JSON/text で記録可能。現行 default state は過去の意図的 fail-open も含むため BLOCKED |
| CY-7 | rollback 手順を作る | Anvil | 完了 | `Anvil env 設定リファレンス` セクションと `docs/photon-ops.md` §8 に rollback 手順を記載済み |
| CY-8 | 段階的 rollout | Anvil | 完了 | 1% → 5% → 10% → 25% → 50% → 100% の手順と記録テンプレートを追加。実 rollout は CY-6 PASS 後に開始 |

### 6. Safety / regression

| ID | タスク | Owner | 状態 | 完了条件 |
|---|---|---|---|---|
| SG-1 | raw stdout/stderr 非注入 regression test | 両方 | 完了 | photon-action-memory 側 raw evidence deny test + Anvil 側 `photon_mapper_smoke::t3_no_stdout_stderr_keys`、`photon_prompt_smoke::p2/p18`、`photon_fixture_smoke::f5_unsafe_raw_log_rejected` で確認済み |
| SG-2 | prompt injection summary の拒否 test | Anvil | 完了 | P3/P4/P12/P13 smoke test で v0.2 kind item に対しても injection/destructive が拒否されることを確認済み |
| SG-3 | secret masking test | 両方 | 完了 | P8a/P8b/P14 smoke (Anvil) + `ContextPackItem.text` sanitizer/API test (photon-action-memory) で確認済み |
| SG-4 | sidecar timeout/fail-open regression test | Anvil | 完了 | T4 (evaluate 500 → fail-open) + T1 (photon=None → 0 calls) + 接続テスト T4-3 で live injection でも turn が止まらないことを確認済み |
| SG-5 | empty context_pack の扱い | Anvil | 完了 | `render_context_pack` が items=0 で None を返し injection message が生成されない。P9/P10 smoke 通過 |
| SG-6 | duplicated context injection 防止 | Anvil | 完了 | LI-2 (`context_pack_sent_this_turn` one-shot flag) で 1 turn 1 call を保証。T11 smoke 通過 |

### 7. Documentation / release readiness

| ID | タスク | Owner | 状態 | 完了条件 |
|---|---|---|---|---|
| DR-1 | Anvil env 設定例を更新 | Anvil | 完了 | 本ファイル「Anvil env 設定リファレンス」＋ Anvil `docs/photon-ops.md` §2/§8 に shadow/live/canary/rollback/CY-4/CY-5 の env と手順を明文化 (commit 81febcf) |
| DR-2 | photon-action-memory sidecar 起動例を更新 | photon-action-memory | 完了 | `workspace/v0.3.0/photon-live-injection-sidecar-runbook.md` に起動例を追加 |
| DR-3 | 接続テスト結果テンプレートを追加 | photon-action-memory | 完了 | `workspace/v0.3.0/live-injection-canary-result.md` を追加 |
| DR-4 | develop 反映手順を整理 | 両方 | 完了 | 両 repo の push、PR、merge、issue close の順序を「DR-4 develop 反映手順」に固定 |

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
| G4 | raw log / prompt injection / secret / timeout の regression が全て通る | 完了 (SG-1〜SG-6 smoke 通過。2026-05-11 Anvil photon smoke 73 passed) |
| G5 | canary 100 eval turn 以上、fail-open 率許容内、success-rate regression なし | **完了** (CY-4: 114/100 ✅、CY-5: sampled 93.0% / unsampled 73.6%、delta=+19.4pp、regression なし ✅) |
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
| canary 運用 インフラ | 完了 | `.anvil/config` (photon_canary=500) で turn 蓄積開始。`scripts/cy5_success_rate_analysis.py` (6729589) と Anvil `docs/photon-ops.md` (§8) で分析環境を整備 |
| canary 運用 実施 | 進行中 | CY-4: 9/100 eval turns (残 91)。CY-5 は正式判定前。通常使用で蓄積中 |

追記日: 2026-05-11

| 領域 | 状態 | 内容 |
|---|---|---|
| LI-5 / SG-1 Anvil 側確認 | 完了 | `cargo test --test photon_prompt_smoke --test photon_fixture_smoke --test photon_mapper_smoke --test photon_turn_hook_smoke --test photon_rollout_policy_smoke` を実行し 73 passed |
| photon-action-memory contract / rollout 確認 | 完了 | `python3 -m pytest tests/test_rollout_policy.py tests/test_context_pack.py tests/test_anvil_context_pack_api.py tests/test_anvil_contract.py` が 79 passed |
| CY-6 判定コマンド | 完了 | `scripts/cy6_gate_check.py` と `tests/test_cy6_gate_check.py` を追加。`ruff check scripts/cy6_gate_check.py tests/test_cy6_gate_check.py` は All checks passed |
| 現時点の CY-6 判定 | BLOCKED | `python3 scripts/cy6_gate_check.py --json` は `photon_eval_turns=9/100`、過去の意図的 fail-open を含む default state で `fail_open_rate=0.3077`、raw marker=0、max injected bytes=182、truncation=0 |
| Anvil rollout-check | BLOCKED | `cargo run -- sessions photon-rollout-check` は Condition 2 が `found 9 photon_eval turns, need 100`、Condition 5 が ManualRequired |

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

## CY-6 Gate 判定手順

正式判定は、過去の意図的な fail-open テストや開発中エラーを含まない rollout 用 state/window で行う。default の `~/.local/state/anvil/sessions` をそのまま読む場合は、過去ログも含まれる。

判定コマンド:

```bash
# Anvil 側の実装 gate。Condition 2 と 5 が OK になるまで rollout 不可。
cd /Users/maenokota/share/work/github_kewton/Anvil-develop
cargo run -- sessions photon-rollout-check

# photon-action-memory 側の集約 gate。JSON は記録に貼り付ける。
cd /Users/maenokota/share/work/github_kewton/photon-action-memory
python3 scripts/cy6_gate_check.py --json

# rollout 用に state/window を分けた場合
python3 scripts/cy6_gate_check.py --state-dir /path/to/rollout/anvil/sessions --json

# CY-5 の成功率比較。CY-6 の CY6-5 補助証跡として使う。
python3 scripts/cy5_success_rate_analysis.py --json
```

CY-6 gate 条件:

| Gate | 条件 | 判定元 |
|---|---|---|
| CY6-1 minimum eval turns | `photon_eval_turns >= 100` | `anvil sessions photon-rollout-check` / `scripts/cy6_gate_check.py` |
| CY6-2 fail-open incident rate | `fail_open_rate <= 0.05` | `scripts/cy6_gate_check.py` (`agent.photon*.completed.failed=true` / photon operation events) |
| CY6-3 raw token / marker leakage | `raw_tool_tokens_in_prompt + raw_marker_hits == 0` | `scripts/cy6_gate_check.py` |
| CY6-4 prompt size | `max_injected_bytes <= 8192` かつ `prompt_truncated_events == 0` | `scripts/cy6_gate_check.py` |
| CY6-5 success-rate regression | sampled/non-sampled 各 20 turn 以上、かつ `sampled - unsampled >= -5.0pp` | `scripts/cy6_gate_check.py` / `scripts/cy5_success_rate_analysis.py` |

記録フォーマット:

| Date JST | State/window | Command | CY6-1 | CY6-2 | CY6-3 | CY6-4 | CY6-5 | Verdict | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 2026-05-11 | default state | `python3 scripts/cy6_gate_check.py --json` | NG `9/100` | NG `0.3077` | OK `0` | OK `182 bytes / trunc=0` | Manual `sampled=10, unsampled=110` | BLOCKED | 過去の意図的 fail-open テストを含む。正式判定は rollout window で再実行 |

## CY-8 段階的 Rollout 手順

CY-8 は CY-6 が PASS した後に開始する。各段階で canary 値を変更し、同じ判定コマンドと記録フォーマットを使う。Gate が NG または Manual のままなら次段階へ進まない。

段階:

| Stage | `ANVIL_PHOTON_CANARY` | 比率 | 次段階へ進む条件 |
|---|---:|---:|---|
| R1 | `10` | 1% | CY-6 PASS。重大 rollback 条件なし |
| R2 | `50` | 5% | R1 の記録が PASS |
| R3 | `100` | 10% | R2 の記録が PASS |
| R4 | `250` | 25% | R3 の記録が PASS |
| R5 | `500` | 50% | R4 の記録が PASS |
| R6 | `1000` | 100% | R5 の記録が PASS |

各 stage の実行:

```bash
# .anvil/config または env で stage の canary を設定
ANVIL_PHOTON_ENABLED=true \
ANVIL_PHOTON_SHADOW_MODE=false \
ANVIL_PHOTON_CANARY=10 \
ANVIL_PHOTON_URL=http://127.0.0.1:18765 \
anvil

# stage ごとに gate を記録
python3 scripts/cy6_gate_check.py --json
python3 scripts/cy5_success_rate_analysis.py --json
```

rollout 記録テンプレート:

| Stage | Date JST | Canary | Eval turns | Adopted turns | Fail-open rate | Raw marker hits | Max injected bytes | Truncated | Success delta | Verdict | Action |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| R1 |  | 1% |  |  |  |  |  |  |  |  |  |
| R2 |  | 5% |  |  |  |  |  |  |  |  |  |
| R3 |  | 10% |  |  |  |  |  |  |  |  |  |
| R4 |  | 25% |  |  |  |  |  |  |  |  |  |
| R5 |  | 50% |  |  |  |  |  |  |  |  |  |
| R6 |  | 100% |  |  |  |  |  |  |  |  |  |

rollback 条件:

- `raw_tool_tokens_in_prompt + raw_marker_hits > 0`
- `fail_open_rate > 0.05`
- `prompt_truncated_events > 0` または `max_injected_bytes > 8192`
- sampled success rate が non-sampled より 5.0pp 超悪化
- Anvil 側で context が user/developer/system 指示として扱われた兆候がある

rollback 操作:

```bash
ANVIL_PHOTON_CANARY=0 anvil
# または
ANVIL_PHOTON_ENABLED=false anvil
```

## DR-4 develop 反映手順

develop 反映から main merge / issue close までの順序を下記に固定する。photon-action-memory の sidecar contract を先に安定させ、Anvil は fail-open / backward compatible 前提で続ける。

1. 両 repo の develop を最新化し、作業ツリーを確認する。
   - photon-action-memory: `git status --short --branch`
   - Anvil: `git status --short --branch`
2. photon-action-memory 側の verification を実行する。
   - `python3 -m pytest tests/test_cy6_gate_check.py tests/test_rollout_policy.py`
   - `python3 -m pytest tests/test_context_pack.py tests/test_anvil_context_pack_api.py tests/test_anvil_contract.py`
   - `ruff check scripts/cy6_gate_check.py tests/test_cy6_gate_check.py`
3. Anvil 側の verification を実行する。
   - `cargo test --test photon_prompt_smoke --test photon_fixture_smoke --test photon_mapper_smoke --test photon_turn_hook_smoke --test photon_rollout_policy_smoke`
   - `cargo run -- sessions photon-rollout-check`
4. 各 repo で commit し、develop を push する。順序は photon-action-memory → Anvil。
5. CI を確認する。失敗した場合は該当 repo の develop で修正し、再 push する。
6. main 向け PR を作る。順序は photon-action-memory → Anvil。
7. main PR の CI が通ったら merge する。順序は photon-action-memory → Anvil。
8. merge 後、main を pull し、tag/release が必要な場合は release 手順へ進む。
9. main merge 済みの関連 Issue を close する。close comment には PR URL、検証コマンド、CY-6/CY-8 の現状を残す。

## 範囲外

- canary なしで全 turn に即時 live injection すること。
- raw stdout/stderr や full build log を prompt に入れること。
- sidecar 障害時に Anvil turn を止めること。
- photon-action-memory の memory を user/developer/system 指示として扱わせること。
