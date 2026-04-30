# photon-mlx からの切り出し計画

## 1. 切り出し方針

`photon-mlx-develop` は RepoRAG 実験基盤として広い責務を持つ。

- repo ingestion
- hybrid retrieval
- symbol graph
- evidence pack
- Qwen generation
- PHOTON working memory
- Safe RecGen
- Streamlit app
- eval harness
- training scripts

`photon-action-memory` では、このうち Coding Agent の action memory に必要な部分だけを切り出す。

基本方針:

- RepoRAG の回答生成 path は持ち込まない。
- PHOTON の階層 working memory / drift / prune の考え方を agent action に転用する。
- DB exporter / sanitizer は早期に移植する。
- sidecar API と schema を先に固定し、model 実装は adapter として後から差し替え可能にする。

## 2. 資産分類

### 2.1 そのまま活用しやすい

| 資産 | 元ファイル | 活用先 |
| --- | --- | --- |
| agent log exporter | `scripts/export_agent_training_data.py` | `training/exporters/mycodebranchdesk.py` |
| sanitizer / path normalization | `scripts/export_agent_training_data.py` | `memory/sanitizer.py` |
| action classification | `scripts/export_agent_training_data.py` | `training/labels.py` |
| PHOTON session state | `photon_mlx/session.py` | `models/photon_state.py` または adapter |
| Safe RecGen thresholds | `photon_mlx/safe_recgen.py` | drift / repeat failure warning |
| eval report culture | `reports/*.md`, `evals/*` | `workspace/eval` と CI metrics |

### 2.2 改造して使う

| 資産 | 元ファイル | 改造内容 |
| --- | --- | --- |
| PHOTON model | `photon_mlx/model.py`, `blocks.py` | RepoRAG latent ではなく agent state/action feature 入力に合わせる |
| inference | `photon_mlx/inference.py` | evidence prune から action candidate ranking へ変更 |
| trainer/data | `photon_mlx/trainer.py`, `data.py` | LM 系 data から trajectory dataset に変更 |
| configs | `configs/photon_small.yaml` など | `configs/action_memory_small.yaml` として再設計 |
| tests | `photon_mlx/tests/*` | shape/config/checkpoint テストを移植し、agent schema テストを追加 |

### 2.3 持ち込まない

| 資産 | 理由 |
| --- | --- |
| `baseline_reporag/generation/*` | final answer generation は本リポジトリの責務外 |
| Streamlit app | 初期は sidecar / CLI / eval を優先 |
| institutional docs eval | Coding Agent action memory の評価軸と異なる |
| Qwen generator integration | Agent 側 LLM が担う |
| RepoRAG citation resolver | action guidance では evidence id / summary で十分 |

## 3. 移植先構成

```text
photon_action_memory/
├── api/
│   ├── schema.py              # Pydantic models, versioned schema
│   ├── server.py              # FastAPI sidecar
│   └── client.py              # Agent-side Python client / smoke client
├── memory/
│   ├── sanitizer.py           # redaction / path normalization
│   ├── store.py               # SQLite event store
│   ├── compaction.py          # tool loop -> compact memory
│   └── cases.py               # reusable case records
├── ranking/
│   ├── candidates.py          # deterministic candidate extraction
│   ├── fallback.py            # model unavailable path
│   └── ranker.py              # PHOTON + heuristic ranking
├── models/
│   ├── photon_adapter.py      # MLX model boundary
│   ├── state.py               # hierarchical state abstraction
│   └── checkpoint.py          # load/save
├── training/
│   ├── exporters/
│   │   └── mycodebranchdesk.py
│   ├── labels.py
│   ├── datasets.py
│   └── train.py
└── eval/
    ├── metrics.py
    ├── fixtures.py
    └── runner.py
```

## 4. 抽出ステージ

### Stage 0: Documentation and skeleton

目的:

- repository intent を固定
- package skeleton を作る
- CI を通す

成果物:

- `pyproject.toml`
- `photon_action_memory/`
- `tests/`
- `.github/workflows/ci.yml`
- schema draft

### Stage 1: Schema and deterministic fallback

目的:

- Anvil から呼べる API contract を先に固定する
- PHOTON model なしでも有用な suggestion を返す

成果物:

- `POST /v1/suggest`
- request / response schema
- file / command / query candidate extractor
- deterministic ranking fallback
- fail-open behavior

### Stage 2: Event store and exporter migration

目的:

- agent trajectory を安全に蓄積できる状態にする
- `photon-mlx` で作成した exporter を移植する

成果物:

- SQLite event store
- sanitizer module
- MyCodeBranchDesk exporter
- temp SQLite regression tests
- redaction report

### Stage 3: PHOTON adapter

目的:

- PHOTON の階層 working memory を action memory ranking に接続する

成果物:

- MLX optional dependency
- checkpoint loader
- action/file/evidence scorer interface
- model unavailable fallback
- macOS MLX smoke test

### Stage 4: Training dataset and objectives

目的:

- Claude / Codex / Anvil logs から action memory 用 dataset を作る

学習対象:

- next action
- target files
- search queries
- useful evidence
- failed action avoidance
- drift / replan signal

成果物:

- JSONL dataset spec
- train/val/test split
- quality labels
- baseline metric
- first small training run

### Stage 5: Anvil shadow integration

目的:

- Anvil の actor loop から suggestion を呼び、行動結果を eval する

成果物:

- Anvil sidecar config
- shadow-mode event logging
- suggestion adoption / ignored / outcome tracking
- offline report

## 5. API 互換性ポリシー

v0.1.x では schema version を必ず含める。

- request の optional field 追加は可
- response の optional field 追加は可
- enum 値追加は minor version 扱い
- required field 削除 / rename は破壊的変更
- 破壊的変更は `v0.2.0` 以降に回す

## 6. データ移行ポリシー

raw logs は直接 commit しない。

許可:

- sanitized JSONL
- aggregate stats
- redaction report
- small synthetic fixtures

禁止:

- raw conversation logs
- raw tool stdout/stderr with secrets
- absolute user home paths
- API keys / tokens / passwords
- proprietary repo content の無断 fixture 化

## 7. photon-mlx 側に残すもの

当面 `photon-mlx-develop` に残す:

- RepoRAG baseline
- institutional eval
- Qwen model matrix
- Streamlit playground
- PHOTON native model research
- existing reports

`photon-action-memory` 側へ移すもの:

- agent trajectory exporter
- action memory schema
- sidecar API
- action ranking eval
- Anvil integration contract
- sanitized coding-agent dataset tooling

## 8. 切り出し時のリスク

| リスク | 対策 |
| --- | --- |
| RepoRAG と action memory の責務混在 | Non-goals を CI/docs で明示 |
| MLX 依存で CI が不安定 | MLX は optional、macOS smoke は別 workflow |
| exporter が secret を漏らす | redaction regression を必須テスト化 |
| Anvil 専用になりすぎる | schema は neutral、Anvil は adapter として扱う |
| model が未学習で価値が出ない | deterministic fallback + shadow eval から始める |
| 過去ログに過適合 | repo split / time split / eval holdout を固定 |

## 9. 初期に移植すべき具体ファイル

優先度順:

1. `scripts/export_agent_training_data.py`
2. `photon_mlx/session.py` の state / drift の概念
3. `photon_mlx/safe_recgen.py` の fallback trigger 設計
4. `photon_mlx/checkpoint.py` の checkpoint handling
5. `photon_mlx/tests/test_config.py`, `test_checkpoint.py`, `test_session.py` の考え方
6. `reports/qwen_model_matrix_20260428_400cmp_report.md` の evaluation report style
