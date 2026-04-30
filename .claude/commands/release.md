---
description: "PHOTON Action Memory のリリースPR、タグ、GitHub Releaseを作成する"
argument-hint: "patch|minor|major|X.Y.Z"
---

# Release Command

`/release` は PHOTON Action Memory のリリースを作成するためのコマンドです。

詳細な手順と安全ルールは `.codex/skills/release/SKILL.md` を正とします。

## 使用方法

```bash
/release patch
/release minor
/release major
/release 1.2.3
```

## 実行方針

- `main` を release base にする。
- `release/vX.Y.Z` branch を作成する。
- `pyproject.toml` と `photon_action_memory/__init__.py` の version を更新する。
- `CHANGELOG.md` を更新する。
- `ruff format --check .`、`ruff check .`、`mypy photon_action_memory tests`、
  `pytest -q`、`python -m build` を通す。
- release PR を `main` 向けに作成する。
- PR が `main` に merge された後で `vX.Y.Z` tag を push する。
- tag push により `.github/workflows/release.yml` が GitHub Release を作成する。

## 注意

- CommandMate の start/stop はユーザーが明示した場合だけ行う。
- `.env`、local DB、raw logs、workspace run artifacts は release commit に含めない。
- tag 作成は release PR merge 後に行う。
