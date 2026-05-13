# Anvil Eval — Beta-Gamma Light Result Template

作成日: 2026-05-13
対象: v0.4.0 P2 `/v1/summarize` integration smoke (Issue #88)

## 目的

`/v1/summarize` を含む turn lifecycle が、Anvil の expanded eval matrix の
代表的な 3 シナリオに対して、

1. **regression detection** — admission policy が `avoid` を落とさない
2. **effect re-evaluation** — `next_hints` がプロンプトに到達する
3. **stability** — 同一シナリオを複数回回しても結果が安定する

を満たすかを軽量に確認する。"beta-gamma-light" の名前は、Anvil eval matrix
の β（regression）と γ（effect）の 2 family を 3 シナリオで横断する
意図から付けた。

## シナリオ

| Scenario | 種別 | 期待 (post-context-pack) | 検出する型 |
|---|---|---|---|
| S2-03 (SvelteKit page edit) | regression | `avoid: React / Next` が `context_pack.items[].text` に残る | S2-03 型 regression |
| S3-01 (calculator.py add bug) | effect | `a + b` および `verify.py` が prompt-visible | S3-01 型効果 |
| S5-01 (tool.py double + ANVIL.md) | effect | `x + x` および `custom_check.py` が prompt-visible | S5-01 型効果 |

S-シナリオの ActionSummary fixture (`tests/fixtures/shared/anvil_eval_s*_action_summary.json`)
は `develop` ブランチで管理する (commits `fc80f54`, `d280e35`)。fixture を
seed する手順は `scripts/seed_expanded_eval_scenarios.sh` で揃えてある。

## 実行条件

sidecar 起動:

```bash
PHOTON_ACTION_MEMORY_DB=/tmp/photon-action-memory-v040-light-events.sqlite \
PHOTON_ACTION_MEMORY_SUMMARY_DB=/tmp/photon-action-memory-v040-light-summaries.sqlite \
python -m uvicorn photon_action_memory.api.server:app \
  --host 127.0.0.1 --port 18765
```

port は `127.0.0.1:18765` のみを使う。port 3000 は使わない。

smoke 実行:

```bash
python3 scripts/anvil_v1_summarize_smoke.py
# または、特定シナリオのみ:
python3 scripts/anvil_v1_summarize_smoke.py --scenario S2-03 --scenario S3-01
```

出力は JSON。各 step の `status` と、`context_pack` step の
`detail.assertion` を確認する:

| `assertion` の値 | 意味 |
|---|---|
| `regression-clear` | S2-03 で `avoid` keyword が残った ✅ |
| `regression-detected` | S2-03 で `avoid` keyword が消えた ❌ |
| `effect-present` | S3-01 / S5-01 の `next_hints` keyword が prompt に出た ✅ |
| `effect-missing` | S3-01 / S5-01 の `next_hints` keyword が prompt に届かなかった ❌ |

CI 連携時は `python3 scripts/anvil_v1_summarize_smoke.py` の終了コードで
判定する。`regression-detected` / `effect-missing` / `error` のいずれかが
1 件でもあれば exit=1。

## 結果記録テンプレート

| Run | Date JST | sidecar commit | scenario | summarize status | context_pack assertion | evaluate logged | Verdict |
|---|---|---|---|---|---|---|---|
| L1 |  |  | S2-03 |  |  |  |  |
| L2 |  |  | S3-01 |  |  |  |  |
| L3 |  |  | S5-01 |  |  |  |  |

`summarize status` 列は `ok` (P1 後) または `summarize_stub` (P1 前)。

## 補足

- `/v1/summarize` が 501 を返す現状でも、smoke は fixture をフォールバック
  として使い `summary_upsert` 以降を実行する。これにより P2 の手順を P1
  着地前から検証できる。
- 本ドキュメントは「light」の名の通り 3 シナリオに限定する。フルの
  expanded eval は Anvil 側 `e2e_uat_matrix.py` を別途回す。
- S2-03 / S3-01 / S5-01 以外のシナリオ追加は、`SCENARIOS` 辞書
  (`scripts/anvil_v1_summarize_smoke.py`) と本テーブルの両方に追記する。
