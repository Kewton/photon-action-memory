# v0.1.0 作業計画

## 1. ゴール

v0.1.0 のゴールは、PHOTON Action Memory を「実装可能な仕様」から「Anvil が shadow-mode で呼べる sidecar」まで進めること。

v0.1.0 では、モデル性能の最終証明までは求めない。まず以下を成立させる。

- sidecar API が動く
- event を安全に保存できる
- suggestion schema が固定される
- deterministic fallback ranking がある
- agent log から sanitized dataset を作れる
- Anvil 統合の入口が明確になる
- evaluation metric が固定される

## 2. Milestone

### M0: Repository bootstrap

成果物:

- `pyproject.toml`
- package skeleton
- README 更新
- CI workflow
- PR template
- basic tests

完了条件:

- `ruff format --check .`
- `ruff check .`
- `pytest -q`
- package build smoke

### M1: Schema first

成果物:

- `SuggestRequest`
- `SuggestResponse`
- `EventRecord`
- `CaseRecord`
- schema versioning
- JSON fixture tests

完了条件:

- Anvil の `WorkingMemory` 相当 payload を受けられる
- unknown optional field で壊れない
- required field 欠落を validation error にできる

### M2: Sidecar MVP

成果物:

- `GET /health`
- `POST /v1/events`
- `POST /v1/suggest`
- fail-open client behavior
- local SQLite event store

完了条件:

- sidecar 起動後に synthetic event を保存できる
- model が無くても suggestion を返せる
- sidecar error 時に client が fallback できる

### M3: Exporter migration

成果物:

- MyCodeBranchDesk exporter 移植
- sanitizer module
- redaction report
- dataset JSONL spec
- temp SQLite fixture tests

完了条件:

- raw absolute user path が出力に残らない
- token / secret pattern が redact される
- next action label が出る
- train/val/test split が作れる

### M4: Ranking baseline

成果物:

- deterministic candidate extractor
- file / query / command ranking
- repeated action detector
- missing evidence warning

完了条件:

- no-model 環境でも suggestion が安定する
- same input に対して deterministic
- repeated search/read を warning できる

### M5: PHOTON adapter

成果物:

- MLX optional dependency
- checkpoint load interface
- action/file/evidence scoring interface
- macOS MLX smoke test

完了条件:

- MLX 未インストールでも package が動く
- checkpoint が無い場合 fallback ranking に戻る
- smoke checkpoint で scoring path が通る

### M6: Evaluation and Anvil shadow contract

成果物:

- offline eval runner
- metrics report
- Anvil sidecar integration contract
- shadow-mode log schema

完了条件:

- fixed fixture で suggestion metric を出せる
- Anvil 側 issue に渡せる integration spec がある
- adoption / ignored / outcome を追跡できる

## 3. Issue 分解案

| 優先 | Issue | 内容 |
| --- | --- | --- |
| P0 | Bootstrap Python package and CI | package skeleton、dev deps、CI |
| P0 | Define v1 sidecar schema | request / response / event schema |
| P0 | Implement sanitizer module | secret / path / control char redaction |
| P0 | Implement local event store | SQLite append/read API |
| P0 | Implement sidecar health/events/suggest | FastAPI MVP |
| P1 | Add deterministic ranking fallback | no-model suggestion |
| P1 | Migrate MyCodeBranchDesk exporter | sanitized dataset export |
| P1 | Add dataset split and stats | train/val/test + label distribution |
| P1 | Add evaluation metrics | hit rate / repeated exploration / latency |
| P2 | Add PHOTON MLX adapter | optional model scoring |
| P2 | Add Anvil shadow-mode contract fixtures | schema compatibility |
| P2 | Add MCP/stdio adapter design | broader agent support |

## 4. 実装順序

推奨順:

1. package skeleton
2. schema
3. sanitizer
4. event store
5. sidecar MVP
6. deterministic ranking
7. exporter migration
8. eval runner
9. PHOTON adapter
10. Anvil shadow integration

理由:

- schema が先にないと Anvil 側と並行開発できない
- sanitizer が先にないと event store / exporter が危険
- model は後から差し替え可能にする方が開発が進む
- deterministic fallback があると PHOTON 未学習でも UX 検証できる

## 5. v0.1.0 の推奨データ戦略

### Phase A: PoC

対象:

- MyCodeBranchDesk の Claude / Codex logs
- 既に作成済みの sanitized JSONL

目安:

- 1,000-5,000 examples
- action distribution の偏りを確認
- secret redaction を検証

### Phase B: MVP

対象:

- Claude / Codex / Anvil logs
- success / failure outcome が取れる session
- repo 単位 split

目安:

- 50,000-300,000 examples
- next action / target files / evidence labels
- time split holdout

### Phase C: Production candidate

対象:

- 多 repo
- 多言語
- 失敗ケース
- user correction / test outcome 付き

目安:

- 500,000+ examples
- repo-local adaptation
- continuous eval

## 6. 学習対象

優先して学習するもの:

- current state -> next action
- current state -> target files
- error output -> suspected files
- task + repo state -> useful search query
- repeated failure -> avoid / replan
- tool history -> compact memory
- final outcome -> trajectory quality

学習しないもの:

- assistant prose style
- final answer の美文
- raw conversation imitation
- repo content の丸暗記
- secret / private path

## 7. 評価計画

### Offline

- fixed JSONL fixture に対する ranking metric
- holdout session replay
- expected next action top-k accuracy
- target file hit rate
- repeated action warning precision
- sanitizer regression

### Shadow-mode

Agent は suggestion を受け取るが、最初は採用しない。

記録:

- suggestion
- actual next action
- whether suggestion matched
- outcome
- latency
- ignored reason if available

### Canary

一部の低リスク action のみ prompt に注入する。

対象:

- read candidates
- search query candidates
- test command candidates

対象外:

- destructive shell command
- edit command auto-approval
- security-sensitive change

## 8. Anvil 組み込み順序

1. Config に sidecar endpoint を追加
2. `WorkingMemory` と recent tool results を request 化
3. actor loop 前に shadow `suggest` を呼ぶ
4. tool result 後に `events` を送る
5. Repo Context v2 で file/evidence candidates を使う
6. Case Retrieval の rerank に使う
7. Plan / Act drift guard に使う
8. 採用率と効果を metrics に出す

## 9. リスクと対策

| リスク | 対策 |
| --- | --- |
| model が未成熟で suggestion が悪い | deterministic fallback と shadow-mode から始める |
| prompt がうるさくなる | top-k と confidence threshold、injection budget を設ける |
| secret leak | sanitizer を event store 前に必ず通す |
| Anvil 専用化 | schema を neutral にし adapter で吸収する |
| CI が MLX 依存で遅い | MLX は optional、macOS smoke は別 workflow |
| ログ品質が低い | quality label、outcome label、failed session filtering を入れる |
| 継続学習で劣化 | offline eval、shadow eval、canary、rollback を必須にする |

## 10. 完了定義

v0.1.0 の Done:

- README と workspace docs がある
- package skeleton と CI がある
- schema が実装されテストされている
- sidecar が起動する
- event store が sanitizer 経由で保存する
- no-model suggestion が返る
- exporter で sanitized JSONL が生成できる
- eval runner が最低限の metrics を出す
- Anvil shadow integration に必要な request / response fixture がある

## 11. v0.1.0 後の展開

v0.2.0:

- PHOTON model scoring を本格化
- Anvil で shadow-mode 実運用
- repo-local adaptation の設計

v0.3.0:

- MCP / stdio adapter
- multi-agent session support
- continuous training pipeline

v1.0:

- stable schema
- documented deployment
- benchmark report
- production-safe privacy policy
