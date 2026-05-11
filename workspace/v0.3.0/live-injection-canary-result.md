# v0.3.0 Live Injection / Canary Result

作成日: 2026-05-09
最終更新: 2026-05-11 JST

## 現在の状況

| 項目 | 状態 | メモ |
|---|---|---|
| photon-action-memory sidecar stored summary auto retrieval | 完了 | `candidate_summary_ids=[]` でも repo/task から stored summary を取得 |
| live injection seed summary fixture | 完了 | `anvil-live-codename-001` |
| seed summary upsert 手順 | 完了 | `scripts/seed_live_injection_summary.py` |
| context pack smoke fixture | 完了 | `tests/fixtures/shared/anvil_live_context_pack_request.json` |
| SG-3 photon secret masking | 完了 | `ContextPackItem.text` 生成時に token/path を mask |
| Anvil live injection 実機 run | 完了 | baseline は答えられず、live injection は `heliograph` を回答 |
| LI-5 / SG-1 Anvil smoke | 完了 | 2026-05-11 に Anvil photon smoke 73 passed |
| CY-6 gate コマンド | 完了 | `scripts/cy6_gate_check.py` 追加。現行 default state は BLOCKED |
| CY-8 rollout テンプレート | 完了 | 1% → 5% → 10% → 25% → 50% → 100% の記録欄を追加 |
| canary rollout | 未開始 | 100 eval turn と success-rate 比較、CY-6 PASS が必要 |

## photon-action-memory 側確認結果

実装した方針:

1. `candidate_summary_ids` がある場合は明示候補を優先。
2. `candidate_summary_ids` が空の場合は `repo.name` で stored summary を自動検索。
3. `repo.name` が空の場合は `repo.root` の basename を repo key として使う。
4. `task.task_signature` がある場合は `repo_id + task_signature` を優先。
5. repo をまたぐ global fallback はしない。

検証:

```bash
PYTHONPATH=. pytest tests/test_context_pack.py tests/test_anvil_context_pack_api.py tests/test_anvil_contract.py
# 65 passed

ruff check photon_action_memory/context/render.py tests/test_context_pack.py photon_action_memory/api/server.py tests/test_anvil_context_pack_api.py scripts/seed_live_injection_summary.py
# All checks passed

scripts/seed_live_injection_summary.py --dry-run
# upsert payload を生成できることを確認
```

SG-3 追加確認:

- `render_summary()` が prompt-visible text を `sanitize_text()` に通す。
- `token=...`, `Bearer ...`, `API_KEY=...` は `[REDACTED_SECRET]` に置換される。
- `/Users/...` 形式のローカル絶対パスは `[ABS_PATH]/...` に正規化される。
- `/v1/context/pack` の stored summary 解決後も raw secret/path は `context_pack.items[].text` に残らない。

## Anvil 実機テスト記録

| Run | 設定 | 期待 | 結果 |
|---|---|---|---|
| baseline | `ANVIL_PHOTON_SHADOW_MODE=false`, `ANVIL_PHOTON_CANARY=0` | codename を memory から答えない | 完了: `photon_context_pack.skipped(reason=canary_gate)`。LLM は repo 内に codename がないため答えられない |
| live injection | `ANVIL_PHOTON_SHADOW_MODE=false`, `ANVIL_PHOTON_CANARY=1000` | prompt に Photon Context が入り `heliograph` を答える | 完了: `The project codename for this repository is heliograph.`。ファイル読み込みなし、iter=1 |
| canary sampled | `ANVIL_PHOTON_SHADOW_MODE=false`, `ANVIL_PHOTON_CANARY=500` | sampled turn のみ prompt 注入 | 進行中: 9/100 photon eval turns。通常使用で蓄積中 |

## LI-5 / SG-1 smoke 結果

Anvil 側:

```bash
cd /Users/maenokota/share/work/github_kewton/Anvil-develop
cargo test --test photon_prompt_smoke --test photon_fixture_smoke --test photon_mapper_smoke --test photon_turn_hook_smoke --test photon_rollout_policy_smoke
# 73 passed
```

確認した内容:

- LI-5: v0.2 `context_pack.items` の unwrap と top-level `items` fallback (`P19/P19b`)。
- LI-5: shared fixture rendering (`F2`) と live mode one-shot call (`T11`)。
- SG-1: mapper が `stdout` / `stderr` キーを送らない (`t3_no_stdout_stderr_keys`)。
- SG-1: non-summary `log` / `raw` item は prompt に出ない (`P2/P18`)。
- SG-1: unsafe raw log fixture は renderer が拒否する (`F5`)。

photon-action-memory 側:

```bash
python3 -m pytest tests/test_rollout_policy.py tests/test_context_pack.py tests/test_anvil_context_pack_api.py tests/test_anvil_contract.py
# 79 passed

python3 -m pytest tests/test_cy6_gate_check.py tests/test_rollout_policy.py
# 16 passed

ruff check scripts/cy6_gate_check.py tests/test_cy6_gate_check.py
# All checks passed
```

## CY-6 gate 結果

現時点の default state (`~/.local/state/anvil/sessions`) は、過去の意図的な fail-open テストと開発中のエラーを含む。そのため現在の結果は rollout 判定としては BLOCKED。正式判定は rollout 用 state/window で再実行する。

```bash
python3 scripts/cy6_gate_check.py --json
```

| Gate | 結果 | 値 | メモ |
|---|---|---|---|
| CY6-1 minimum eval turns | NG | `9/100` | 100 turn 未達 |
| CY6-2 fail-open incident rate | NG | `0.3077` | 過去の意図的 fail-open を含む |
| CY6-3 raw token / marker leakage | OK | `0` | raw marker なし |
| CY6-4 prompt size | OK | `max_injected_bytes=182`, `prompt_truncated_events=0` | cap 内 |
| CY6-5 success-rate regression | Manual | `sampled=10`, `unsampled=110` | sampled が 20 turns 未満 |

Anvil 実装 gate:

```bash
cd /Users/maenokota/share/work/github_kewton/Anvil-develop
cargo run -- sessions photon-rollout-check
# Condition 2: found 9 photon_eval turns, need 100
# Condition 5: ManualRequired
```

## CY-8 rollout 記録テンプレート

| Stage | Date JST | Canary | Eval turns | Adopted turns | Fail-open rate | Raw marker hits | Max injected bytes | Truncated | Success delta | Verdict | Action |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| R1 |  | 1% |  |  |  |  |  |  |  |  |  |
| R2 |  | 5% |  |  |  |  |  |  |  |  |  |
| R3 |  | 10% |  |  |  |  |  |  |  |  |  |
| R4 |  | 25% |  |  |  |  |  |  |  |  |  |
| R5 |  | 50% |  |  |  |  |  |  |  |  |  |
| R6 |  | 100% |  |  |  |  |  |  |  |  |  |

## 実行メモ

sidecar 起動:

```bash
PHOTON_ACTION_MEMORY_DB=/tmp/photon-action-memory-v030-live-events.sqlite \
PHOTON_ACTION_MEMORY_SUMMARY_DB=/tmp/photon-action-memory-v030-live-summaries.sqlite \
python -m uvicorn photon_action_memory.api.server:app --host 127.0.0.1 --port 18765
```

seed:

```bash
scripts/seed_live_injection_summary.py --url http://127.0.0.1:18765
```

context pack:

```bash
curl -sS http://127.0.0.1:18765/v1/context/pack \
  -H 'Content-Type: application/json' \
  --data @tests/fixtures/shared/anvil_live_context_pack_request.json
```
