# v0.1.0 開発準備作業計画

## 0. 現在の開発状況

最終更新: 2026-04-30

リポジトリ状態:

- 現在ブランチは `develop`。
- 作業ツリーは clean。
- `develop` は PR #1 `chore: bootstrap Python package` の merge 済み状態。
- M0 Repository bootstrap は完了済み。

完了済み:

- `develop` ブランチ作成。
- M0 作業ブランチ `chore/bootstrap-python-package` 作成。
- `pyproject.toml` 作成。
- `photon_action_memory/` package skeleton 作成。
- `tests/test_import.py` basic smoke test 作成。
- `.github/workflows/ci.yml` 作成。
- `.github/pull_request_template.md` 作成。
- `.gitignore`、`configs/README.md`、`scripts/README.md` 作成。
- `README.md` に development commands 追記。
- `workspace/v0.1.0/05_development_preparation_plan.md` 作成。

M0 検証結果:

- `ruff format --check .`: pass
- `ruff check .`: pass
- `mypy photon_action_memory tests`: pass
- `pytest -q`: pass
- `python -m build`: pass

GitHub issue 登録状況:

| Issue | 優先 | Milestone | 内容 | 状態 |
| --- | --- | --- | --- | --- |
| [#2](https://github.com/Kewton/photon-action-memory/issues/2) | P0 | M1 | Define v1 sidecar schema | Open |
| [#3](https://github.com/Kewton/photon-action-memory/issues/3) | P0 | M3 | Implement sanitizer module | Open |
| [#4](https://github.com/Kewton/photon-action-memory/issues/4) | P0 | M2 | Implement local SQLite event store | Open |
| [#5](https://github.com/Kewton/photon-action-memory/issues/5) | P0 | M2 | Implement sidecar health/events/suggest | Open |
| [#6](https://github.com/Kewton/photon-action-memory/issues/6) | P1 | M4 | Add deterministic ranking fallback | Open |
| [#7](https://github.com/Kewton/photon-action-memory/issues/7) | P1 | M3 | Migrate MyCodeBranchDesk exporter | Open |
| [#8](https://github.com/Kewton/photon-action-memory/issues/8) | P1 | M3 | Add dataset split and stats | Open |
| [#9](https://github.com/Kewton/photon-action-memory/issues/9) | P1 | M6 | Add evaluation metrics | Open |
| [#10](https://github.com/Kewton/photon-action-memory/issues/10) | P1 | M6 | Add Anvil shadow-mode contract fixtures | Open |
| [#11](https://github.com/Kewton/photon-action-memory/issues/11) | P2 | M5 | Add PHOTON MLX adapter | Open |
| [#12](https://github.com/Kewton/photon-action-memory/issues/12) | P2 | M5 | Add checkpoint load interface | Open |
| [#13](https://github.com/Kewton/photon-action-memory/issues/13) | P2 | M5 | Add macOS MLX smoke workflow | Open |
| [#14](https://github.com/Kewton/photon-action-memory/issues/14) | P2 | - | Add MCP / stdio adapter design note | Open |

次の推奨作業:

1. `feature/schema-first` などのブランチを `develop` から作成する。
2. [#2](https://github.com/Kewton/photon-action-memory/issues/2) の M1 schema-first 実装から着手する。
3. schema が固まり次第、[#3](https://github.com/Kewton/photon-action-memory/issues/3) sanitizer、[#4](https://github.com/Kewton/photon-action-memory/issues/4) event store、[#5](https://github.com/Kewton/photon-action-memory/issues/5) sidecar MVP の順に進める。

## 1. 目的

この文書は、`README.md`、`workspace/v0.1.0/01-04` の設計文書、および以下の参照元ソースを確認したうえで、`photon-action-memory` の実装開始に必要な準備作業を具体化する。

参照元:

- `/Users/maenokota/share/work/github_kewton/photon-mlx-develop`

v0.1.0 では、PHOTON を RepoRAG / final answer generation から切り離し、Coding Agent 向けの Action-Oriented Memory sidecar として成立させる。最初の開発準備では、model 実装よりも schema、sanitizer、event store、deterministic fallback、CI を優先する。

## 2. 現状認識

`photon-action-memory` 側の現状:

- ルート `README.md` と `workspace/v0.1.0` の設計文書が存在する。
- `pyproject.toml`、package skeleton、tests、CI workflow は M0 で作成済み。
- 現在ブランチは `develop`。
- 作業ツリーは clean。

`photon-mlx-develop` 側の参照対象:

- `scripts/export_agent_training_data.py`
  - MyCodeBranchDesk SQLite logs から sanitized state/action/evidence JSONL を生成する exporter。
  - secret/path/email/control character redaction、tool/action classification、file path extraction、quality scoring、redaction report が含まれる。
- `photon_mlx/session.py`
  - hierarchical state、turn history、drift metrics、working memory config、storage mode validation。
  - Action Memory では raw latent 保持ではなく、drift / topic shift / compact state の考え方を利用する。
- `photon_mlx/safe_recgen.py`
  - exact quote / diff / high-risk query / drift / confidence による fallback trigger。
  - Action Memory では repeat failure、missing evidence、drift guard、replan warning に転用する。
- `photon_mlx/checkpoint.py`
  - runtime-only checkpoint I/O、integrity hash、unknown state key の forward compatibility。
  - Action Memory では optional PHOTON adapter の checkpoint boundary として後段で利用する。
- `photon_mlx/tests/test_checkpoint.py`
  - runtime import boundary、integrity validation、forward compatibility のテスト方針。
- `photon_mlx/tests/test_safe_recgen.py`
  - classifier / fallback trigger / fail-closed config validation のテスト方針。
- `photon_mlx/tests/test_session.py`
  - drift metrics、hierarchical scoring、storage behavior のテスト方針。
- `.github/workflows/weekly_eval.yml`
  - heavy eval / real checkpoint test を通常 CI から分ける運用例。

注意:

- `photon-mlx-develop` の作業ツリーには未追跡ファイルが多い。移植時は読み取り専用で参照し、必要なロジックだけを新リポジトリへ再構成する。
- checkpoint、raw logs、大容量 eval output は `photon-action-memory` に commit しない。

## 3. 開発準備の基本方針

1. `develop` を統合ブランチにし、`main` は release 基点にする。
2. 最初の PR は M0 bootstrap に限定し、実装の土台だけを作る。
3. schema と sanitizer を event store より先に実装する。
4. PHOTON / MLX は optional dependency にし、通常 CI の必須 gate に入れない。
5. sidecar は fail-open を前提にし、model unavailable 時は deterministic fallback ranking を返す。
6. exporter は raw log dump ではなく、sanitized trajectory dataset generator として移植する。
7. Anvil 統合は v0.1.0 では shadow-mode contract までに留める。

## 4. 参照元からの移植マッピング

| 参照元 | 新規配置 | 初期対応 |
| --- | --- | --- |
| `scripts/export_agent_training_data.py` の redaction regex / `sanitize_text` | `photon_action_memory/memory/sanitizer.py` | P0 で移植。event store 前に必ず通す |
| `scripts/export_agent_training_data.py` の action classification | `photon_action_memory/training/labels.py` と `ranking/candidates.py` | P0/P1。training label と fallback candidate に分離 |
| `scripts/export_agent_training_data.py` の JSONL writer / stats | `photon_action_memory/training/datasets.py` | P1。split / stats と統合 |
| `photon_mlx/session.py` の `DriftMetrics` / finite coercion | `photon_action_memory/models/state.py` または `memory/compaction.py` | P2。MLX 非依存 DTO から始める |
| `photon_mlx/safe_recgen.py` の query classifier / fallback decision | `photon_action_memory/ranking/guards.py` | P1。repeat / missing evidence warning と統合 |
| `photon_mlx/checkpoint.py` の runtime-only I/O boundary | `photon_action_memory/models/checkpoint.py` | P2。MLX adapter 着手時に移植 |
| `photon_mlx/tests/test_safe_recgen.py` | `tests/test_guards.py` | P1。classifier / warning trigger の regression test |
| `photon_mlx/tests/test_checkpoint.py` | `tests/integration/test_mlx_smoke.py` と `tests/test_checkpoint.py` | P2。optional MLX boundary の検証 |
| `.github/workflows/weekly_eval.yml` | `.github/workflows/eval-shadow.yml` | P2。nightly/manual eval に転用 |

持ち込まないもの:

- `baseline_reporag/generation/*`
- Streamlit app
- institutional docs eval 固有の corpus / reports
- Qwen generator integration
- raw logs / checkpoints / sandbox outputs

## 5. ブランチと Issue 準備

### 5.1 ブランチ

初期作業:

1. `main` から `develop` を作成する。
2. M0 は `chore/bootstrap-python-package` で作業する。
3. 以降は issue 単位で `feature/...` または `fix/...` を切る。

初期の常設ブランチ:

| ブランチ | 用途 |
| --- | --- |
| `main` | release / tag 基点 |
| `develop` | v0.1.0 統合先 |

### 5.2 初期 Issue

P0:

- [x] Bootstrap Python package and CI: PR #1 で完了
- [ ] [#2](https://github.com/Kewton/photon-action-memory/issues/2) Define v1 sidecar schema
- [ ] [#3](https://github.com/Kewton/photon-action-memory/issues/3) Implement sanitizer module
- [ ] [#4](https://github.com/Kewton/photon-action-memory/issues/4) Implement local SQLite event store
- [ ] [#5](https://github.com/Kewton/photon-action-memory/issues/5) Implement sidecar health/events/suggest

P1:

- [ ] [#6](https://github.com/Kewton/photon-action-memory/issues/6) Add deterministic ranking fallback
- [ ] [#7](https://github.com/Kewton/photon-action-memory/issues/7) Migrate MyCodeBranchDesk exporter
- [ ] [#8](https://github.com/Kewton/photon-action-memory/issues/8) Add dataset split and stats
- [ ] [#9](https://github.com/Kewton/photon-action-memory/issues/9) Add evaluation metrics
- [ ] [#10](https://github.com/Kewton/photon-action-memory/issues/10) Add Anvil shadow-mode contract fixtures

P2:

- [ ] [#11](https://github.com/Kewton/photon-action-memory/issues/11) Add PHOTON MLX adapter
- [ ] [#12](https://github.com/Kewton/photon-action-memory/issues/12) Add checkpoint load interface
- [ ] [#13](https://github.com/Kewton/photon-action-memory/issues/13) Add macOS MLX smoke workflow
- [ ] [#14](https://github.com/Kewton/photon-action-memory/issues/14) Add MCP / stdio adapter design note

## 6. M0 Bootstrap 詳細計画

成果物:

- `pyproject.toml`
- `photon_action_memory/`
- `tests/`
- `.github/workflows/ci.yml`
- `.github/pull_request_template.md`
- `configs/`
- `scripts/`
- basic smoke test

推奨 package skeleton:

```text
photon_action_memory/
├── __init__.py
├── api/
│   ├── __init__.py
│   ├── schema.py
│   ├── server.py
│   └── client.py
├── memory/
│   ├── __init__.py
│   ├── sanitizer.py
│   ├── store.py
│   └── compaction.py
├── ranking/
│   ├── __init__.py
│   ├── candidates.py
│   ├── fallback.py
│   └── guards.py
├── models/
│   ├── __init__.py
│   ├── photon_adapter.py
│   ├── state.py
│   └── checkpoint.py
├── training/
│   ├── __init__.py
│   ├── labels.py
│   ├── datasets.py
│   └── exporters/
│       ├── __init__.py
│       └── mycodebranchdesk.py
└── eval/
    ├── __init__.py
    ├── metrics.py
    └── runner.py
```

初期 dependency:

- runtime: `pydantic`, `fastapi`, `uvicorn`, `httpx`
- dev: `pytest`, `ruff`, `mypy`, `build`
- optional: `mlx`

初期 CI:

- `ruff format --check .`
- `ruff check .`
- `mypy photon_action_memory tests`
- `pytest -q`
- `python -m build`

完了条件:

- 空の package を import できる。
- CI workflow が Ubuntu で通る構成になっている。
- MLX が未インストールでも import / tests が通る。
- PR template に schema / sanitizer / fail-open 確認項目がある。

## 7. M1 Schema First 詳細計画

成果物:

- `SuggestRequest`
- `SuggestResponse`
- `EventRecord`
- `CaseRecord`
- `EvaluationRecord`
- `SchemaVersion`
- JSON fixture tests

設計ポイント:

- `schema_version` は request / response / event に必須。
- unknown optional field は許容する。
- required field 欠落は validation error にする。
- enum は拡張前提にし、未知値を受ける場所と拒否する場所を明確化する。
- Anvil 固有 field は `agent.name == "anvil"` と `metadata` に逃がし、core schema は neutral に保つ。

初期 fixtures:

- minimal suggest request
- Anvil WorkingMemory 相当 payload
- recent tool result payload
- malformed required field missing
- unknown optional metadata included

完了条件:

- JSON fixture round-trip が通る。
- Anvil shadow-mode request の最小形を表現できる。
- schema version policy が README または docstring に明記されている。

## 8. M2 Sidecar MVP 詳細計画

成果物:

- `GET /health`
- `POST /v1/events`
- `POST /v1/suggest`
- `POST /v1/summarize` stub
- `POST /v1/evaluate` stub
- fail-open Python client
- SQLite event store

実装順:

1. schema validator
2. sanitizer
3. SQLite append/read API
4. health endpoint
5. events endpoint
6. suggest endpoint
7. fail-open client

MVP の挙動:

- `POST /v1/events` は sanitizer を通した payload のみ保存する。
- `POST /v1/suggest` は model 不在でも deterministic fallback を返す。
- sidecar error / timeout 時、client は空 suggestion と warning を返し agent を止めない。
- `summarize/evaluate` は v0.1.0 の scope に含まれるが、M2 では stub または `501 Not Implemented` で contract を固定する。

完了条件:

- synthetic event を SQLite に保存できる。
- health check が成功する。
- model / checkpoint なしで suggestion が返る。
- client timeout test が fail-open を確認する。

## 9. M3 Sanitizer / Exporter 詳細計画

`photon-mlx-develop/scripts/export_agent_training_data.py` を参考にするが、単一 script のまま移植しない。以下に分割する。

| 機能 | 新規 module |
| --- | --- |
| redaction regex / text cleanup | `memory/sanitizer.py` |
| absolute path normalization | `memory/sanitizer.py` |
| tool name extraction | `training/labels.py` |
| next action classification | `training/labels.py` |
| file path extraction | `ranking/candidates.py` |
| JSONL writing / split | `training/datasets.py` |
| MyCodeBranchDesk SQLite reader | `training/exporters/mycodebranchdesk.py` |

sanitizer regression:

- API key / token / bearer / password assignment を redact する。
- `sk-...` など secret-like long token を redact する。
- email を `[EMAIL]` に置換する。
- `/Users/...`、`/home/...`、`/tmp/...` を raw のまま残さない。
- ANSI escape と制御文字を除去する。
- secret を含む path candidate を除外する。

dataset spec:

- `example_id`
- `schema_version`
- `source`
- `task`
- `state`
- `label`
- `quality`
- `redaction`

完了条件:

- temp SQLite fixture から sanitized JSONL を生成できる。
- redaction report が出る。
- raw absolute user path が output に残らない。
- secret pattern が output に残らない。
- train / val / test split を deterministic に作れる。

## 10. M4 Deterministic Ranking 詳細計画

成果物:

- candidate extractor
- file / query / command ranking
- repeated action detector
- missing evidence warning
- no-model ranker

初期 ranking rules:

- recent error に file path がある場合、read / inspect candidate を上位にする。
- touched files と target files の overlap を優先する。
- recent tools に同一 `read` / `search` が複数ある場合、repeat warning を出す。
- test/build error がある場合、関連 test command を候補にする。
- evidence が不足している edit request では `missing_evidence` warning を出す。
- destructive shell command は suggestion に出さない。

`safe_recgen.py` から転用する考え方:

- high-risk query classifier
- confidence floor
- drift / topic shift trigger
- fallback decision の details 形式

完了条件:

- same input に対して同じ ordering を返す。
- top-k limit と evidence char budget を守る。
- repeated search/read を warning できる。
- model unavailable が通常経路として test されている。

## 11. M5 PHOTON Adapter 詳細計画

成果物:

- `models/photon_adapter.py`
- `models/checkpoint.py`
- `models/state.py`
- optional `mlx` extra
- macOS smoke workflow

設計ポイント:

- runtime import で `mlx` を強制しない。
- `photon_mlx.checkpoint.py` と同様に checkpoint I/O は training dependency から分離する。
- checkpoint integrity check は optional strict mode を持つ。
- unknown checkpoint state key は warning で drop する。
- checkpoint missing / invalid / MLX missing 時は fallback ranking に戻す。

初期 scorer interface:

```text
score_actions(state, candidates) -> list[ScoredCandidate]
score_files(state, files) -> list[ScoredFile]
score_evidence(state, evidence) -> list[ScoredEvidence]
```

完了条件:

- MLX 未導入環境で package import と tests が通る。
- MLX 導入環境で tiny smoke が通る。
- checkpoint 不在時に fallback ranking へ戻る。
- checkpoint integrity failure が明示的に失敗する。

## 12. M6 Eval / Anvil Shadow Contract 詳細計画

成果物:

- offline eval runner
- fixed fixture dataset
- metrics report
- Anvil shadow-mode request / response fixture
- shadow evaluation event schema

metrics:

- next action top-k accuracy
- target file hit rate
- useful evidence hit rate
- repeated exploration warning precision
- fail-open incident count
- p50 / p95 suggest latency

shadow-mode log schema:

- request id
- suggestion ids
- actual next action
- suggestion matched
- ignored reason
- outcome
- latency
- sidecar status

完了条件:

- fixed fixture で metrics が出る。
- Anvil 側 issue に渡せる integration contract がある。
- adoption / ignored / outcome を追跡できる。
- eval runner は raw log を直接吐かない。

## 13. 実装順チェックリスト

### Phase 0: Repository bootstrap

- [x] `develop` ブランチ作成
- [x] M0 用 feature branch 作成
- [x] `pyproject.toml` 作成
- [x] package skeleton 作成
- [x] tests skeleton 作成
- [x] CI workflow 作成
- [x] PR template 作成
- [x] basic import test
- [x] PR #1 merge

### Phase 1: Contract first

- [ ] [#2](https://github.com/Kewton/photon-action-memory/issues/2) schema models 実装
- [ ] [#2](https://github.com/Kewton/photon-action-memory/issues/2) schema fixtures 追加
- [ ] [#2](https://github.com/Kewton/photon-action-memory/issues/2) Anvil WorkingMemory 相当 fixture 追加
- [ ] [#2](https://github.com/Kewton/photon-action-memory/issues/2) schema compatibility tests

### Phase 2: Privacy first

- [ ] [#3](https://github.com/Kewton/photon-action-memory/issues/3) sanitizer 実装
- [ ] [#3](https://github.com/Kewton/photon-action-memory/issues/3) redaction tests
- [ ] [#3](https://github.com/Kewton/photon-action-memory/issues/3) path normalization tests
- [ ] [#3](https://github.com/Kewton/photon-action-memory/issues/3) control character tests
- [ ] [#4](https://github.com/Kewton/photon-action-memory/issues/4) event store 前 sanitizer の強制

### Phase 3: Sidecar first run

- [ ] [#4](https://github.com/Kewton/photon-action-memory/issues/4) SQLite event store
- [x] [#5](https://github.com/Kewton/photon-action-memory/issues/5) FastAPI server
- [x] [#5](https://github.com/Kewton/photon-action-memory/issues/5) fail-open client
- [x] [#5](https://github.com/Kewton/photon-action-memory/issues/5) synthetic event smoke
- [x] [#5](https://github.com/Kewton/photon-action-memory/issues/5) no-model suggest smoke

### Phase 4: Dataset and ranking

- [ ] [#7](https://github.com/Kewton/photon-action-memory/issues/7) MyCodeBranchDesk exporter 移植
- [ ] [#8](https://github.com/Kewton/photon-action-memory/issues/8) dataset JSONL spec
- [ ] [#8](https://github.com/Kewton/photon-action-memory/issues/8) deterministic split
- [x] [#6](https://github.com/Kewton/photon-action-memory/issues/6) candidate extractor
- [x] [#6](https://github.com/Kewton/photon-action-memory/issues/6) fallback ranker
- [x] [#6](https://github.com/Kewton/photon-action-memory/issues/6) repeated action / missing evidence warning

### Phase 5: Model and eval

- [ ] [#11](https://github.com/Kewton/photon-action-memory/issues/11) MLX optional extra
- [ ] [#11](https://github.com/Kewton/photon-action-memory/issues/11) PHOTON adapter interface
- [ ] [#12](https://github.com/Kewton/photon-action-memory/issues/12) checkpoint I/O
- [ ] [#13](https://github.com/Kewton/photon-action-memory/issues/13) macOS smoke workflow
- [ ] [#9](https://github.com/Kewton/photon-action-memory/issues/9) offline eval runner
- [ ] [#10](https://github.com/Kewton/photon-action-memory/issues/10) Anvil shadow contract

## 14. 初回 PR の推奨スコープ

初回 PR は M0 のみに限定する。

含める:

- `pyproject.toml`
- package / tests skeleton
- CI workflow
- PR template
- README の開発コマンド追記
- smoke test

含めない:

- exporter 移植
- SQLite schema
- FastAPI endpoint 実装
- MLX adapter
- checkpoint / model logic
- raw dataset / reports / checkpoints

理由:

- 開発土台と CI を先に固定すると、以降の schema / sanitizer / sidecar の PR を小さく分けられる。
- sanitizer と event store を同時に入れる前に、test / lint / typecheck の境界を作れる。
- MLX を後回しにすることで、通常 CI が platform dependency に引きずられない。

## 15. 開発開始前の確認事項

- [x] `develop` ブランチを作成してよいか。
  - 作成済み。PR #1 merge 後の統合先として利用中。
- [x] package manager は標準 `pip` / `pyproject.toml` で進めるか、`uv` を採用するか。
  - M0 では標準 `pip` / `pyproject.toml` で開始済み。
- [x] Python version は docs 通り 3.12 で固定してよいか。
  - `pyproject.toml` と CI で Python 3.12 を指定済み。
- [x] MyCodeBranchDesk DB は local-only 入力として扱い、raw fixture は commit しない方針でよいか。
  - `.gitignore` と issue #7 の完了条件に反映済み。
- [x] `POST /v1/summarize` と `POST /v1/evaluate` は M2 では stub、M6 で実体化する方針でよいか。
  - issue #5 と #10 に反映済み。
