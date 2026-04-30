# Codex オーケストレーションハーネス実現タスク

作成日: 2026-04-30

## 1. ゴール

`workspace/management/codex_harness_spec.md` の仕様を実現し、ユーザーが次のように Issue 番号を指定するだけで、Issue 整備、並列可否判断、git worktree 作成、CommandMate 経由の Codex セッション起動、設計、実装、テスト、PR 作成、develop 反映、UAT 手順生成、報告までを進められる状態にする。

```text
/orchestrate {issue A} {issue B} {issue C} ...
```

CommandMate 上の Codex カスタムコマンドは以下の仕組みで提供する。

- worktree local skill: `.codex/skills/<name>/SKILL.md` -> CommandMate 上では `/<name>`
- worktree local prompt: `.codex/prompts/<name>.md` -> CommandMate 上では `/prompts:<name>`
- global skill: `~/.codex/skills/<name>/SKILL.md`
- global prompt: `~/.codex/prompts/<name>.md`

このリポジトリでは、まず worktree local の `.codex/skills` と `.codex/prompts` を作り、リポジトリに同梱できる形を基本とする。

## 2. 成果物一覧

| 種別 | Path | 目的 |
| --- | --- | --- |
| 仕様 | `workspace/management/codex_harness_spec.md` | 実行仕様 |
| タスク | `workspace/management/codex_harness_tasks.md` | 本タスク一覧 |
| Skill | `.codex/skills/orchestrate/SKILL.md` | CommandMate 上の `/orchestrate` |
| Skill | `.codex/skills/codex-issue-worker/SKILL.md` | 各 worktree の設計・実装・テスト worker |
| Skill | `.codex/skills/codex-create-pr/SKILL.md` | PR 作成 |
| Skill | `.codex/skills/codex-uat/SKILL.md` | UAT 手順生成と結果整理 |
| Prompt | `.codex/prompts/orchestrate-worker.md` | worker に送る task prompt template |
| Prompt | `.codex/prompts/uat-manual-check.md` | 実機 / GUI 確認手順 template |
| Script | `scripts/codex_orchestrate.py` | dry-run planning と orchestration 実行 |
| Script | `scripts/commandmate_codex.py` | `commandmatedev` adapter |
| Template | `workspace/management/templates/*.md` | manifest / report / PR / UAT template |
| Tests | `tests/test_codex_orchestrate_*.py` | planning / naming / prompt / parser の unit tests |

## 3. 残タスク一覧

現時点の実装は、dry-run planning、worktree 作成 manager、CommandMate 送信入口、processing polling、PR 作成入口、mergeability 判定、merge 後 integration verification、UAT 手順生成、UAT failure follow-up prompt 生成、UAT fix worktree 作成、Issue 本文反映 diff / 更新、`rg` による影響ファイル補強、PHOTON event fail-open 連携まで完了している。

残タスクは次の 2 件。

| 優先 | 対応 Milestone | 残タスク | 必要な理由 | 完了条件 |
| --- | --- | --- | --- | --- |
| P2 | M0/M10 | CommandMate UI 上でカスタムコマンド候補を実機確認する | ファイル配置は済みだが UI 候補表示は手元の CommandMate 画面確認が必要 | Codex 入力欄で `/orchestrate` と `/prompts:orchestrate-worker` が候補表示される |
| P2 | M9/M10 | PHOTON event の実 sidecar 送信確認 | fail-open 実装は入ったが、実 sidecar が受信・保存できるかの確認が必要 | `--photon-url` 指定時に sidecar へ event が保存され、`photon-events.md` に sent として残る |

### 今すぐ実装するべき順序

1. CommandMate UI 候補表示の手動確認
2. PHOTON event の実 sidecar 送信確認

### 2026-04-30 実機検証結果

Issue 2, 3, 4, 5 を対象に、実 worktree 作成から CommandMate の Codex worker 送信までを実行した。

結果:

- Issue 2: `/Users/maenokota/share/work/github_kewton/photon-action-memory-issue-2-p0-m1-define-v1-sidecar-schema`
  - branch: `feature/issue-2-p0-m1-define-v1-sidecar-schema`
  - commit: `2432c3e Issue #2 define v1 sidecar schema`
  - verification: `python -m pytest -q` -> 13 passed, `ruff check .` -> passed, `ruff format --check .` -> passed
- Issue 3: `/Users/maenokota/share/work/github_kewton/photon-action-memory-issue-3-p0-m3-implement-sanitizer-module`
  - branch: `feature/issue-3-p0-m3-implement-sanitizer-module`
  - commit: `3f0950f feat(issue-3): implement sanitizer module`
  - verification: `python -m pytest -q` -> 12 passed, `ruff check .` -> passed, `ruff format --check .` -> passed
- Issue 4: `/Users/maenokota/share/work/github_kewton/photon-action-memory-issue-4-p0-m2-implement-local-sqlite-event-store`
  - branch: `feature/issue-4-p0-m2-implement-local-sqlite-event-store`
  - commit: `95c454a Issue #4 implement SQLite event store`
  - verification: `python -m pytest -q` -> 7 passed, `ruff check .` -> passed, `ruff format --check .` -> passed
- Issue 5: `/Users/maenokota/share/work/github_kewton/photon-action-memory-issue-5-p0-m2-implement-sidecar-health-events-suggest`
  - branch: `feature/issue-5-p0-m2-implement-sidecar-health-events-suggest`
  - commit: `c172796 Issue #5: implement sidecar MVP`
  - verification: `python -m pytest -q` -> 9 passed, `ruff check .` -> passed, `ruff format --check .` -> passed

確認できたこと:

- `commandmatedev send --agent codex` で対象 worktree の Codex セッションへ prompt を送信できる。
- CommandMate 側の worktree id は、path basename ではなく `repositoryName-branchName` 形式になる。
- `commandmatedev ls --json` は配列を返す環境があり、parser は list / object の両対応が必要。
- `commandmatedev wait` の Completed は、必ずしも「実装完了、テスト完了、commit 済み」を意味しない。最終判定は `git status`、`git log origin/develop..HEAD`、verification artifact で行う。
- repository local `.codex` がまだ develop に取り込まれていない worktree では `/codex-issue-worker` が利用できないため、worker prompt は slash command に依存しない直接手順を含める必要がある。この fallback は実装済み。

## 4. Milestone

### M0: ドキュメントとカスタムコマンド骨格

目的:

- CommandMate 上で `/orchestrate` などの Codex 用コマンドが候補表示される土台を作る。
- まだ実行自動化せず、手動運用できる prompt と手順を固定する。

タスク:

- [x] `.codex/skills/orchestrate/SKILL.md` を作成する。
- [x] `.codex/skills/codex-issue-worker/SKILL.md` を作成する。
- [x] `.codex/skills/codex-create-pr/SKILL.md` を作成する。
- [x] `.codex/skills/codex-uat/SKILL.md` を作成する。
- [x] `.codex/prompts/orchestrate-worker.md` を作成する。
- [x] `.codex/prompts/uat-manual-check.md` を作成する。
- [x] `workspace/management/templates/manifest.md` を作成する。
- [x] `workspace/management/templates/issue-analysis.md` を作成する。
- [x] `workspace/management/templates/dependency-plan.md` を作成する。
- [x] `workspace/management/templates/final-report.md` を作成する。
- [ ] CommandMate で `/orchestrate` と `/prompts:orchestrate-worker` が候補に出ることを確認する。

完了条件:

- worktree 画面を開き直すか再取得した後、CommandMate の Codex 入力欄で `/` 候補に追加 skill / prompt が出る。
- `/orchestrate` の説明が、仕様書の Phase 0-9 と一致している。
- 既存の `.claude/commands` に依存しない。

### M1: Dry-run planner

目的:

- Issue を fetch し、軽量分析、詳細化要否、並列化計画、worktree 名、branch 名、merge order を dry-run で出せるようにする。

タスク:

- [x] `scripts/codex_orchestrate.py` を追加する。
- [x] CLI 引数を実装する: issue list, `--dry-run`, `--max-parallel`, `--phase`, `--merge-order`, `--skip-enhance`。
- [x] `gh issue view` で Issue title/body/labels/comments を取得する。
- [x] Issue から目的、受入条件、推定影響ファイル、テスト期待値を抽出する。
- [x] 詳細化が必要な Issue を判定する。
- [x] 詳細化質問を最大 3 つに制限する。
- [x] GitHub Issue 本文に反映する候補 section を生成する。
- [x] `rg` を使って推定影響ファイルを補強する。
- [x] Issue 間の独立 / 弱い衝突 / 強い衝突 / ブロックを分類する。
- [x] branch 名と worktree path を生成する。
- [x] `workspace/management/runs/<run_id>/manifest.md` を生成する。
- [x] `issue-analysis.md` と `dependency-plan.md` を生成する。

完了条件:

- `python scripts/codex_orchestrate.py 1 2 --dry-run` が worktree や branch を作らず計画だけ出す。
- Issue 本文が曖昧な場合、質問案を生成する。
- 明確な不足修正は GitHub Issue 反映候補として出る。
- 同じ入力に対して run_id 以外の計画が安定する。

### M2: GitHub Issue 詳細化反映

目的:

- ユーザー確認後、Issue 詳細化結果を GitHub Issue 本文へ反映できるようにする。

タスク:

- [x] 詳細化 section の Markdown format を決める。
- [x] 既存 Issue 本文に同 section がある場合の update 方針を実装する。
- [x] `gh issue edit` または GitHub plugin 経由の更新処理を実装する。
- [x] dry-run 時は diff だけ出す。
- [x] 反映結果を `issue-enhancement-report.md` に記録する。

完了条件:

- ユーザー承認ありの場合のみ Issue 本文を更新する。
- 既存本文を破壊せず、追記または管理 section 更新に留める。
- 更新前後の差分が run artifact に残る。

### M3: Worktree manager

目的:

- planned worktree を安全に作成・再利用できるようにする。

タスク:

- [x] `origin/develop` を fetch する処理を実装する。
- [x] `feature/issue-<number>-<slug>` branch の存在確認を実装する。
- [x] worktree path の存在確認を実装する。
- [x] 既存 worktree の dirty check を実装する。
- [x] 新規 worktree 作成を実装する。
- [x] 既存 dirty worktree がある場合は停止し、ユーザー確認が必要な状態として記録する。
- [x] 作成結果を `worker-sessions.md` に記録する。

完了条件:

- clean な既存 worktree は再利用候補になる。
- dirty な既存 worktree は自動上書きされない。
- `git worktree add` の対象は `origin/develop`。

### M4: CommandMate adapter

目的:

- `commandmatedev` を通じて各 worktree の Codex セッションを起動、監視、capture できるようにする。

タスク:

- [x] `scripts/commandmate_codex.py` を追加する。
- [x] `commandmatedev ls --json` の parser を実装する。
- [x] worktree id 解決を実装する。
- [x] `hello` 送信を実装する。
- [x] task prompt 送信を実装する。
- [x] 既定では Anvil 側と同じく `--agent` を付けない。
- [x] `codex_agent_name` が設定されている場合だけ `--agent <name>` を付ける。
- [x] processing 状態の polling を実装する。
- [x] stuck worker に `"a"` または短い resume prompt を送る retry を実装する。
- [x] `commandmatedev capture <id> --json` の取得を実装する。

完了条件:

- dry-run では送信コマンドだけが出る。
- 実行モードでは `hello` -> task prompt -> polling -> capture の流れを実行できる。
- worker が idle のままなら blocked として記録する。

### M5: Worker skill / prompt 実行

目的:

- 各 worktree の Codex セッションが、設計、実装、テスト、commit、PR readiness まで進む標準 prompt を使えるようにする。

タスク:

- [x] `.codex/skills/codex-issue-worker/SKILL.md` に worker 手順を実装する。
- [x] `.codex/prompts/orchestrate-worker.md` に task prompt template を実装する。
- [x] worker prompt に Issue summary / 受入条件 / dependency notes を差し込めるようにする。
- [x] worker 成果物 path を `dev-reports/issue-<number>/` に固定する。
- [x] focused verification の記録 format を決める。
- [x] broader verification の実行条件を prompt に明記する。
- [x] blocker 報告 format を決める。

完了条件:

- CommandMate 上で `/codex-issue-worker` が候補に出る。
- worker prompt が過剰レビューを抑制する。
- worker の完了報告から changed files / tests / blockers を抽出できる。

### M6: PR creation flow

目的:

- worker 完了後に develop 向け PR を作成し、PR 情報を orchestration run に紐づける。

タスク:

- [x] `.codex/skills/codex-create-pr/SKILL.md` を実装する。
- [x] PR body template を作成する。
- [x] Issue link、summary、changed files、tests run、known risks、orchestration run ID を PR body に入れる。
- [x] `gh pr create` または GitHub plugin 経由の PR 作成を実装する。
- [x] 既存 PR がある場合の検出を実装する。
- [x] PR 番号を `worker-sessions.md` または `merge-report.md` に記録する。

完了条件:

- 各 Issue branch から develop 向け PR を作成できる。
- 既存 PR がある場合は重複作成しない。
- PR body に tests run が必ず入る。

### M7: Merge pipeline

目的:

- 開発は並列、merge は順次という方針で、develop へ安全に反映する。

タスク:

- [x] PR merge order を `dependency-plan.md` から読み込む。
- [x] `gh pr checks` または GitHub plugin で CI status を確認する。
- [x] mergeability を確認する。
- [x] repository default の merge method で merge する。
- [x] repository policy が不明、または method 選択が必要な場合はユーザー確認に回す。
- [x] merge 後に orchestrator worktree を更新する。
- [x] integration verification を実行する。
- [x] verification failure 時に merge line を停止する。
- [x] failure を原因 Issue に mapping する。

完了条件:

- CI failure の PR はユーザー承認なしに merge しない。
- develop verification failure 後は後続 PR を merge しない。
- merge 結果は `merge-report.md` に残る。

### M8: UAT 手順生成と fix loop

目的:

- 自動チェックだけでなく、実機 / GUI 確認の手順を生成し、失敗時は修正ループへ戻せるようにする。

タスク:

- [x] `.codex/skills/codex-uat/SKILL.md` を実装する。
- [x] `.codex/prompts/uat-manual-check.md` を実装する。
- [x] Issue 受入条件から UAT scenario を生成する。
- [x] 自動確認可能な項目と手動確認が必要な項目を分離する。
- [x] 実機 / GUI 確認手順の format を決める。
- [x] evidence 欄を設計する: screenshot, log, 操作動画, 確認者メモ。
- [x] UAT 失敗時に Issue / PR / file へ mapping する。
- [x] focused failure prompt を生成する。
- [x] fix branch / worktree の作成または再利用を実装する。
- [x] retry limit 3 を実装する。

完了条件:

- `uat-report.md` に自動チェック結果と手動確認手順が分かれて出る。
- GUI / 実機確認が必要な Issue でも、ユーザーがそのまま実施できる手順が出る。
- UAT failure から follow-up worker prompt を生成できる。

### M9: PHOTON Action Memory 連携

目的:

- orchestration の成功・失敗を将来の再利用に回せるよう、PHOTON 側へ normalized event を送る。

タスク:

- [x] event schema を `orchestrate.started` などの event kind に合わせて整理する。
- [x] PHOTON sidecar がない場合は fail-open にする。
- [x] worker startup failure を event 化する。
- [x] verification failure を event 化する。
- [x] UAT failure / passed を event 化する。
- [ ] successful Issue completion を compact case として保存する方針を決める。
- [ ] run summary metrics を `workspace/eval/runs/codex-orchestrate/<run_id>/report.md` に出す。

完了条件:

- PHOTON event emission failure で orchestration が止まらない。
- 最低限の event が run artifact と sidecar に二重で追跡できる。

### M10: 統合テストと運用確認

目的:

- 小さい Issue で end-to-end に近い流れを検証する。

タスク:

- [x] dry-run planner の unit tests を追加する。
- [x] branch / worktree naming の unit tests を追加する。
- [x] Issue analysis parser の unit tests を追加する。
- [x] CommandMate adapter の subprocess mock tests を追加する。
- [x] PR body generator の unit tests を追加する。
- [x] UAT report generator の unit tests を追加する。
- [x] 1 Issue の dry-run -> worktree -> worker prompt dispatch までを手動検証する。
- [x] 2 Issue の independent parallel planning を検証する。
- [x] weak conflict / strong conflict の計画を fixture で検証する。

完了条件:

- `pytest -q` で追加 tests が通る。
- dry-run なしの最小手順で、CommandMate に worker prompt を送れる。
- 実運用前に、merge を伴わない rehearsal run ができる。

## 5. 実装順序

推奨順:

1. M0: Codex カスタムコマンド骨格
2. M1: Dry-run planner
3. M3: Worktree manager
4. M4: CommandMate adapter
5. M5: Worker skill / prompt 実行
6. M6: PR creation flow
7. M7: Merge pipeline
8. M8: UAT 手順生成と fix loop
9. M2: GitHub Issue 詳細化反映
10. M9: PHOTON Action Memory 連携
11. M10: 統合テストと運用確認

M2 は重要だが、最初は run artifact への出力だけで planning と worker dispatch を検証できるため、GitHub 本文更新は safety を固めてから実装する。

## 6. 最初の Issue 分解案

| Issue 案 | 優先 | 内容 |
| --- | --- | --- |
| Codex custom command skeleton | P0 | `.codex/skills` と `.codex/prompts` を追加し、CommandMate 上で候補表示できるようにする |
| Dry-run orchestration planner | P0 | Issue fetch、軽量分析、依存計画、run artifact 生成 |
| Worktree and branch manager | P0 | `origin/develop` ベースの worktree 作成・再利用・dirty check |
| CommandMate Codex adapter | P0 | `commandmatedev` 経由の hello、prompt 送信、polling、capture |
| Worker prompt and reports | P0 | `/pm-auto-design2dev` 相当の軽量 worker skill / prompt と `dev-reports` format |
| PR creation support | P1 | PR body template、PR 作成、既存 PR 検出 |
| Sequential merge pipeline | P1 | CI / mergeability / repository default merge / develop verification |
| UAT manual procedure generator | P1 | 実機 / GUI 確認手順、evidence format、UAT report |
| UAT fix loop | P2 | failure mapping、follow-up worktree、retry limit |
| GitHub Issue enhancement writer | P2 | 詳細化結果の Issue 本文反映 |
| PHOTON event integration | P2 | orchestration event と compact case 記録 |

## 7. リスクと対策

| リスク | 対策 |
| --- | --- |
| CommandMate の Codex agent 名が環境で異なる | 既定は `--agent` なし。必要な場合だけ `codex_agent_name` を設定 |
| worker が idle / ready のまま処理しない | Anvil 側と同じく `hello` -> task -> processing 確認 -> retry を実装 |
| Issue 詳細化が重くなりすぎる | 詳細化条件を限定し、質問は最大 3 つに制限 |
| 並列開発で conflict が増える | weak / strong conflict 分類と merge order を必須 artifact にする |
| PR merge method が曖昧 | repository default を使い、不明な場合だけユーザー確認 |
| UAT が自動化できない | 実機 / GUI 手順、期待結果、evidence を生成し、ユーザー確認へ渡す |
| 既存 worktree の変更を壊す | dirty check で停止し、自動 reset / delete を禁止 |
| PHOTON sidecar 障害で止まる | PHOTON 連携は fail-open。run artifact には warning を残す |

## 8. 次に着手する具体タスク

現在の実装済み slice:

1. [x] `.codex/skills/orchestrate/SKILL.md` を追加する。
2. [x] `.codex/prompts/orchestrate-worker.md` を追加する。
3. [x] `workspace/management/templates/manifest.md` を追加する。
4. [x] `workspace/management/templates/dependency-plan.md` を追加する。
5. [x] `scripts/codex_orchestrate.py --dry-run` の skeleton を追加する。
6. [x] 1 Issue の dry-run で `manifest.md` と `issue-analysis.md` を出せるようにする。
7. [x] 実 worktree 作成 manager を追加する。
8. [x] CommandMate adapter を追加する。
9. [x] PR 作成支援を追加する。
10. [x] merge pipeline の入口を追加する。
11. [x] UAT report と UAT failure 用 follow-up prompt 生成を追加する。
12. [x] CommandMate processing polling と stuck worker retry を追加する。
13. [x] mergeability 判定と integration verification command を追加する。
14. [x] UAT failure から fix worktree を作成する処理を追加する。
15. [x] GitHub Issue 本文反映 diff / update を追加する。
16. [x] `rg` による影響ファイル補強と external reference 分離を追加する。
17. [x] PHOTON event fail-open 送信を追加する。

次に残る具体タスク:

1. [x] `commandmatedev` の processing polling を実機で固める。
2. [ ] CommandMate UI で Codex カスタムコマンド候補を確認する。
3. [ ] `--photon-url` 指定で実 sidecar に event が保存されることを確認する。
