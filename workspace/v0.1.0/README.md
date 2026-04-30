# photon-action-memory v0.1.0 Workspace

このディレクトリは、`photon-action-memory` の初期開発に向けた設計・移行・運用計画をまとめる。

## 目的

`photon-action-memory` は、PHOTON を Coding Agent のための **Action-Oriented Memory Layer** として切り出すリポジトリである。

既存の `photon-mlx-develop` は RepoRAG / multi-turn retrieval / PHOTON working memory の実験資産を多く持つ。一方で、新リポジトリでは用途を絞り、Anvil や Codex 系コーディングエージェントから使える **local-first sidecar** として成立させる。

## ドキュメント一覧

| ファイル | 内容 |
| --- | --- |
| `01_spec_requirements_architecture.md` | 仕様、要件、アーキテクチャ |
| `02_branch_strategy_ci.md` | ブランチ戦略、CI パイプライン定義 |
| `03_photon_mlx_extraction_plan.md` | `photon-mlx` からの切り出し計画 |
| `04_work_plan.md` | v0.1.0 作業計画 |

## v0.1.0 の基本方針

- PHOTON を「回答生成モデル」ではなく「行動記憶コントローラ」として扱う。
- Agent 本体を置き換えず、fail-open の sidecar として組み込む。
- 最初の統合対象は Anvil とする。
- RAG 化ではなく、tool loop / repo exploration / next action selection を主対象にする。
- オンライン学習ではなく、ログ蓄積、sanitize、offline training、shadow evaluation の順で安全に改善する。

## 参照元資産

- `photon-mlx-develop`
  - PHOTON model/session/safe recgen/training/eval/exporter 資産
- `Anvil-develop`
  - local-first coding agent runtime、working memory、case retrieval、CI/branch 運用
