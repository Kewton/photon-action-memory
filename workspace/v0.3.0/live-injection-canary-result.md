# v0.3.0 Live Injection / Canary Result

作成日: 2026-05-09

## 現在の状況

| 項目 | 状態 | メモ |
|---|---|---|
| photon-action-memory sidecar stored summary auto retrieval | 完了 | `candidate_summary_ids=[]` でも repo/task から stored summary を取得 |
| live injection seed summary fixture | 完了 | `anvil-live-codename-001` |
| seed summary upsert 手順 | 完了 | `scripts/seed_live_injection_summary.py` |
| context pack smoke fixture | 完了 | `tests/fixtures/shared/anvil_live_context_pack_request.json` |
| SG-3 photon secret masking | 完了 | `ContextPackItem.text` 生成時に token/path を mask |
| Anvil live injection 実機 run | 未着手 | Anvil 側 live injection 実装後に実施 |
| canary rollout | 未着手 | 100 eval turn と success-rate 比較が必要 |

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

## Anvil 実機テスト記録欄

Anvil 側 live injection 実装後に追記する。

| Run | 設定 | 期待 | 結果 |
|---|---|---|---|
| baseline | `ANVIL_PHOTON_ENABLED=false` または `ANVIL_PHOTON_CANARY=0` | codename を memory から答えない | 未実施 |
| live injection | `ANVIL_PHOTON_SHADOW_MODE=false`, `ANVIL_PHOTON_CANARY=1000` | prompt に Photon Context が入り `heliograph` を答える | 未実施 |
| canary sampled | `ANVIL_PHOTON_SHADOW_MODE=false`, `ANVIL_PHOTON_CANARY=10` など | sampled turn のみ prompt 注入 | 未実施 |

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
