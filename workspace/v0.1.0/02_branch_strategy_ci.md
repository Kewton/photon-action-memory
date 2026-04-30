# ブランチ戦略、CI パイプライン定義

## 1. 参考にする Anvil の運用

Anvil は以下の構成を採用している。

- `main` / `develop` を対象に push / pull_request で CI を実行
- format、lint、test、build を分離した job として実行
- Rust 本体だけでなく、補助 Python script も `ruff` と snapshot/security test で検証
- tag `v*` push で release workflow を実行
- PR template で変更種別と検証項目を明示

`photon-action-memory` では、同じ考え方を Python / MLX / sidecar / dataset exporter 向けに調整する。

## 2. ブランチ戦略

### 2.1 常設ブランチ

| ブランチ | 役割 | ルール |
| --- | --- | --- |
| `main` | リリース済み安定版 | 直接 push 禁止。tag release の基点 |
| `develop` | 次リリース統合 | PR merge の標準ターゲット |

### 2.2 作業ブランチ

| 種別 | 命名 | 用途 |
| --- | --- | --- |
| feature | `feature/issue-123-short-name` | 新機能 |
| fix | `fix/issue-123-short-name` | バグ修正 |
| chore | `chore/issue-123-short-name` | CI、依存、docs、整理 |
| experiment | `experiment/name` | 評価実験。merge 前に成果を feature に整理 |
| release | `release/v0.1.0` | release candidate 固定 |

### 2.3 マージ方針

- default target は `develop`
- `develop` から `main` へは release PR で昇格
- feature branch は issue 単位を基本にする
- model artifact や大容量 dataset は Git に入れない
- generated eval reports は `workspace/` 配下に置き、必要な summary のみ commit 対象にする

### 2.4 リリース方針

- version tag は `v0.1.0` 形式
- release PR で以下を固定する
  - changelog
  - schema version
  - migration note
  - eval summary
  - known limitations

## 3. CI パイプライン

### 3.1 必須 job

| Job | Trigger | 目的 |
| --- | --- | --- |
| `format` | PR / push | `ruff format --check` |
| `lint` | PR / push | `ruff check` |
| `typecheck` | PR / push | `mypy` または `pyright` |
| `unit-test` | PR / push | pure Python unit tests |
| `schema-test` | PR / push | request / response schema compatibility |
| `security-test` | PR / push | sanitizer / redaction regression |
| `exporter-test` | PR / push | temp SQLite から dataset export smoke |
| `build` | PR / push | package build smoke |

### 3.2 条件付き job

| Job | Trigger | 目的 |
| --- | --- | --- |
| `mlx-smoke` | `develop` push / nightly / manual | macOS runner で MLX import + tiny scoring smoke |
| `integration-anvil-schema` | PR label / manual | Anvil request fixture との schema compatibility |
| `eval-shadow` | nightly / manual | fixed fixture に対する suggestion metric |
| `release` | tag `v*` | wheel / sdist publish artifact 作成 |

## 4. 推奨 GitHub Actions 定義

初期 `.github/workflows/ci.yml` の方針:

```yaml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

env:
  PYTHON_VERSION: "3.12"

jobs:
  python:
    name: Python checks
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
      - name: Install
        run: |
          python -m pip install -U pip
          pip install -e ".[dev]"
      - name: Format
        run: ruff format --check .
      - name: Lint
        run: ruff check .
      - name: Typecheck
        run: mypy photon_action_memory tests
      - name: Tests
        run: pytest -q

  build:
    name: Build package
    runs-on: ubuntu-latest
    needs: [python]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Build
        run: |
          python -m pip install -U pip build
          python -m build
```

MLX smoke は初期から必須にしない。Ubuntu runner で壊れる依存を PR の標準 gate に入れると開発速度を落とすため、macOS job は `develop` / nightly / manual gate に置く。

```yaml
name: MLX Smoke

on:
  workflow_dispatch:
  schedule:
    - cron: "0 18 * * *"
  push:
    branches: [develop]

jobs:
  mlx-smoke:
    runs-on: macos-14
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install
        run: |
          python -m pip install -U pip
          pip install -e ".[dev,mlx]"
      - name: Smoke
        run: pytest -q tests/integration/test_mlx_smoke.py
```

## 5. Release workflow

Anvil は tag `v*` で binary artifact を作る。`photon-action-memory` は Python package なので、初期は以下にする。

- tag `v*` で `sdist` / `wheel` を build
- GitHub Release に artifact upload
- PyPI publish は手動または trusted publishing 設定後に有効化

```yaml
name: Release

on:
  push:
    tags:
      - "v*"

permissions:
  contents: write

jobs:
  package:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Build package
        run: |
          python -m pip install -U pip build
          python -m build
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/*

  release:
    needs: [package]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist
      - name: Create GitHub Release
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: gh release create "${{ github.ref_name }}" --generate-notes dist/*
```

## 6. PR template

Anvil の template を踏襲しつつ、PHOTON Action Memory 用の確認項目を追加する。

```markdown
## 概要

## 変更内容
-

## 関連Issue
Closes #

## 変更の種類
- [ ] 新機能
- [ ] バグ修正
- [ ] リファクタリング
- [ ] ドキュメント
- [ ] CI/CD
- [ ] データ/評価
- [ ] API schema 変更

## テスト
- [ ] `ruff format --check .`
- [ ] `ruff check .`
- [ ] `mypy photon_action_memory tests`
- [ ] `pytest -q`
- [ ] schema compatibility を確認
- [ ] sanitizer / redaction regression を確認

## API / Data 影響
- [ ] request / response schema に破壊的変更なし
- [ ] dataset format に破壊的変更なし
- [ ] secret / PII を raw 保存していない
- [ ] fail-open 挙動を維持している
```

## 7. Branch protection

`main`:

- PR 必須
- CI 必須
- release PR 以外の直接 merge を避ける
- tag は `main` の commit から作成

`develop`:

- PR 必須
- `format` / `lint` / `unit-test` / `schema-test` 必須
- macOS MLX smoke は初期は advisory、v0.2 以降で必須化を検討

## 8. CI で守る品質境界

初期から必ず守るべき境界:

- schema は後方互換を壊さない
- sanitizer は token / secret / absolute path を漏らさない
- sidecar failure は agent failure にしない
- exporter は raw DB を丸ごと吐かない
- model unavailable 時は deterministic fallback ranking に戻る
