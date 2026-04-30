# Codex オーケストレーションハーネス仕様

作成日: 2026-04-30

## 1. 目的

ユーザーが次のように Issue 番号だけを指定すると、Codex 用の開発ハーネスが Issue 整備、並列可否判定、worktree 作成、CommandMate 経由の Codex セッション起動、設計から実装、PR 作成、develop 反映、報告までを進める。

```text
/orchestrate {issue A} {issue B} {issue C} ...
```

期待するユーザー体験:

- ユーザーは Issue 番号を渡すだけでよい。
- ハーネスは不足情報だけを短く確認する。
- ハーネスは並列化できる Issue を並列に進める。
- 各 Issue は個別 worktree の Codex セッションで、設計、実装、テスト、PR 作成まで進む。
- develop へ順次取り込み、必要なら UAT 相当の受入テストを実施する。
- ユーザーは最終結果の確認、実機テスト、必要な判断だけを行う。

この文書は、`/Users/maenokota/share/work/github_kewton/Anvil-develop` の Claude Code / CommandMate 向けハーネスを、`photon-action-memory` リポジトリ上で Codex 向けに再利用するための実行仕様である。

## 2. 初期スコープ外

次は初期スコープ外とする。

- Claude Code の `.claude/commands` をそのまま実行可能にすること。
- Issue を過剰にレビューして、開発開始までを重くすること。
- 全 Issue を常に並列化すること。
- Codex セッションに無制限の権限を渡すこと。
- PHOTON Action Memory sidecar が落ちた場合に開発自体を止めること。

PHOTON Action Memory は、初期段階では行動ログ、評価、再利用可能な失敗・成功ケースの記録先として扱う。開発オーケストレーションの主役は CommandMate + Codex + git worktree である。

## 3. 参照元との対応

| Anvil-develop 側の資産 | 元の役割 | Codex ハーネスでの扱い |
| --- | --- | --- |
| `.claude/commands/orchestrate.md` | 複数 Issue の全体統括 | `/orchestrate` の主仕様 |
| `.claude/commands/issue-enhance.md` | Issue 詳細化 | 不足情報だけを補う軽量な Issue 詳細化 |
| `.claude/commands/multi-stage-issue-review.md` | 多段 Issue レビュー | 必要時のみ縮小版として実施 |
| `.claude/commands/pm-auto-design2dev.md` | 設計から実装まで | 各 worktree の Codex セッションに送る主タスク |
| `.claude/commands/create-pr.md` | PR 作成 | 各 Issue worktree で実行する PR 作成タスク |
| `.claude/commands/pr-merge-pipeline.md` | PR 順次 merge | develop 反映フェーズ |
| `.claude/commands/uat.md` | 受入テスト | develop 反映後の UAT |
| `.claude/commands/uat-fix-loop.md` | UAT fail 修正 | 受入失敗時の修正ループ |
| `workspace/orchestration/*` | オーケストレーション方法論 | runbook / artifact layout |
| `workspace/eval/*` | 評価 matrix / reports | Codex run tracking と品質評価 |

## 4. トップレベルコマンド

### 4.1 形式

```text
/orchestrate <issue_number> [<issue_number> ...] [options]
```

オプション:

| オプション | 意味 |
| --- | --- |
| `--full` | develop 反映後の UAT と fix loop まで行う |
| `--phase issue|plan|dev|pr|merge|uat` | 指定フェーズまで実行する |
| `--max-parallel N` | 同時に走らせる worktree / Codex セッション数 |
| `--merge-order A,B,C` | develop への反映順を明示する |
| `--skip-enhance` | Issue 詳細化を省略する |
| `--dry-run` | worktree 作成や Codex 起動をせず計画だけ出す |

初期既定値:

- `--phase merge`
- `--max-parallel 3`
- `--full` 未指定時も、実機/GUI 確認が必要な場合は UAT 手順を生成する
- Issue 詳細化は不足・矛盾がある場合のみ行う
- develop の取得元は `origin/develop`
- PR merge method はリポジトリ既定に従う

### 4.2 前提条件

- orchestrator は develop ブランチ相当の統合 worktree で実行する。
- `commandmatedev` が利用可能である。
- GitHub issue / PR を確認できる。
- 対象リポジトリで `git worktree` を作成できる。
- 各 Codex セッションが実行できる CommandMate 環境がある。

確認コマンド例:

```bash
git branch --show-current
commandmatedev ls
gh issue view <issue> --json number,title,body,labels
```

### 4.3 CommandMate 上でのカスタムコマンド提供

Codex 用のカスタム定義は、CommandMate 上で次の形で候補表示される。

| 配置 | CommandMate 上の表示 | 用途 |
| --- | --- | --- |
| `./.codex/skills/<name>/SKILL.md` | `/<name>` | worktree local の実行手順 |
| `./.codex/prompts/<name>.md` | `/prompts:<name>` | worktree local の prompt template |
| `~/.codex/skills/<name>/SKILL.md` | `/<name>` | global skill |
| `~/.codex/prompts/<name>.md` | `/prompts:<name>` | global prompt |

このハーネスでは、まず repository local の `.codex/skills` / `.codex/prompts` を使う。`/orchestrate` は `.codex/skills/orchestrate/SKILL.md` として提供し、worker 用の長い task prompt は `.codex/prompts/orchestrate-worker.md` に分離する。

Codex 用カスタム定義は都度読み込みなので、追加後は対象 worktree 画面を開き直すか再取得して反映する。

## 5. 実行フロー

```text
Phase 0  run manifest 作成
Phase 1  Issue 取得と軽量な詳細化
Phase 2  依存関係と並列化計画の整理
Phase 3  worktree 作成
Phase 4  commandmatedev 経由で Codex セッション起動
Phase 5  各 worktree で設計 -> 実装 -> テスト
Phase 6  PR 作成
Phase 7  PR を develop へ順次反映
Phase 8  UAT と fix loop
Phase 9  最終報告
```

## 6. 各フェーズの詳細

### Phase 0: Run Manifest 作成

実行ごとに次のディレクトリを作成する。

```text
workspace/management/runs/YYYYMMDD-HHMMSS-orchestrate/
  manifest.md
  issue-analysis.md
  dependency-plan.md
  worker-sessions.md
  merge-report.md
  uat-report.md
  final-report.md
```

`manifest.md` に含めるもの:

- 指定された Issue 番号
- repository full name
- 開始時の branch / commit
- 指定オプション
- 最大並列数
- CommandMate の Codex 起動設定
- 検証コマンド
- ユーザーへの質問と回答

### Phase 1: Issue 取得と軽量な詳細化

各 Issue について以下を行う。

1. title、body、labels、必要なら comments を取得する。
2. 次を抽出する。
   - 目的
   - 期待動作
   - 影響ファイルまたは module
   - 受入条件
   - テスト期待値
   - 制約 / 非ゴール
3. 詳細化が必要か判断する。

詳細化を行う条件:

- 受入条件が欠けている
- 期待動作が曖昧
- Issue 本文やコードから影響範囲を推定できない
- 指定された別 Issue と衝突している
- product / design 判断が必要
- security、migration、破壊的操作のリスクがある

詳細化は軽量にする。

- 一度にユーザーへ聞く質問は最大 3 つ。
- yes/no または短く答えられる質問を優先する。
- 実装安全性に影響する曖昧さがない限り、多段レビューはしない。
- 内容の不足が明確な場合は GitHub Issue 本文へ反映する。
- GitHub Issue 本文へ反映するほどではない補足は run artifact に残す。

出力:

```text
issue-analysis.md
```

推奨構造:

```markdown
## Issue #123

- タイトル:
- 種別: feature|bug|docs|refactor|test|unknown
- 目的:
- 受入条件:
- 推定影響ファイル:
- テストコマンド:
- 曖昧な点:
- 詳細化要否: yes|no
- ユーザーへの質問:
- GitHub Issue 反映内容:
```

### Phase 2: 依存関係と並列化計画の整理

各 Issue を分類する。

| 分類 | 意味 | スケジューリング |
| --- | --- | --- |
| 独立 | 変更ファイルや product 依存が重ならない | 並列 |
| 弱い衝突 | 近い領域を触るが変更箇所は分離できる | 並列可。ただし merge 順を管理 |
| 強い衝突 | 同じ file / 関数、または直接依存がある | 直列 |
| ブロック | 判断不足または前提不足 | ユーザー確認または skip |

入力:

- Issue 本文
- labels
- 推定影響ファイル
- `rg` による repository inspection
- Issue 間の関係
- 必要な場合の branch / PR 履歴

出力:

```text
dependency-plan.md
```

必須内容:

- Issue group
- planned worktree name
- branch name
- parallel batch
- merge order
- risk note
- blocked item

branch 名:

```text
feature/issue-<number>-<short-slug>
```

worktree path:

```text
../<repo-name>-issue-<number>-<short-slug>
```

### Phase 3: worktree 作成

実行可能な Issue ごとに worktree を作成する。

```bash
git fetch origin develop
git worktree add -b "feature/issue-<number>-<slug>" "../<repo>-issue-<number>-<slug>" origin/develop
```

ルール:

- branch / worktree が既にある場合は、再利用前に状態を確認する。
- 既存 worktree は自動削除しない。
- 既存 worktree に未コミット変更がある場合は停止してユーザーへ確認する。
- worktree path と branch は `worker-sessions.md` に記録する。

### Phase 4: CommandMate 経由で Codex セッション起動

orchestrator は Issue worktree ごとに CommandMate セッションを起動する。

Anvil 側の `.claude/commands/orchestrate.md` では、通常ワーカーへの task 送信に `--agent` を付けていない。Codex 版もこれに合わせ、初期既定では `--agent` を指定しない。CommandMate 側で Codex 専用 agent 名が必要な環境だけ、設定で `--agent <name>` を付けられるようにする。

既定のコマンド形:

```bash
commandmatedev send <worktree-id> "hello"
commandmatedev send <worktree-id> "<codex task prompt>" --auto-yes --duration 3h
```

Codex agent 名を明示する環境でのコマンド形:

```bash
commandmatedev send <worktree-id> "<codex task prompt>" --agent <codex-agent-name> --auto-yes --duration 3h
```

起動の堅牢化:

1. セッションが idle / ready の場合は先に `hello` を送る。
2. worktree が running / ready になるまで待つ。
3. task prompt を送る。
4. `commandmatedev ls --json` または CommandMate API で processing 状態を確認する。
5. セッションが開始しない場合は、短い resume message で 1 回だけ retry する。
6. それでも idle の場合は worker を blocked として記録し、ユーザーへ報告する。

### Phase 5: 設計 -> 実装 -> テスト

各 worker には `/pm-auto-design2dev` 相当の prompt を送る。ただし、過剰レビューを避けるため軽量化する。

worker prompt template:

```text
あなたは Issue #<number> 専用の git worktree で作業しています。

目的:
- Issue #<number> を、Issue 本文と orchestration notes に従って実装してください。

実施内容:
1. Issue summary と関連ファイルを読む。
2. 編集前に短い design note を書く。
3. 最小で一貫した実装を行う。
4. 必要に応じて focused test を追加・更新する。
5. まず focused verification を実行する。
6. 共有領域に触れた場合は broader verification も実行する。
7. 明確な commit message で commit する。
8. develop 向け PR を準備する。

レビューは軽量にしてください:
- Issue が曖昧または高リスクでない限り、多段レビューはしない。
- 質問は blocking question のみにする。
- Issue 全体の書き直しより、local design note を優先する。

必須出力:
- 変更ファイル summary
- 実行した test と結果
- PR readiness status
- blocker があればその内容

Issue:
<issue summary>

受入条件:
<criteria>

Orchestration notes:
<dependency / merge / risk notes>
```

worker が作成する成果物:

```text
dev-reports/issue-<number>/
  design.md
  implementation-summary.md
  verification.md
```

検証方針:

- 常に最も focused な relevant check を実行する。
- 共有 module、API schema、storage、ranking、eval、CI-sensitive な領域を触る場合は broader check も実行する。
- check を実行できない場合は理由を記録する。

### Phase 6: PR 作成

完了した worker ごとに以下を行う。

1. branch に commit 済み変更があることを確認する。
2. verification result を確認する。
3. develop 向け PR を作成する。
4. PR 番号を記録する。

PR 作成方法:

- worker session が context を持っている場合は、worker に PR 作成まで任せる。
- worker が clean に完了している場合は、orchestrator が GitHub plugin / `gh` で直接 PR を作成してもよい。

PR body に含めるもの:

- Issue link
- summary
- changed files
- tests run
- known risks
- orchestration run ID

### Phase 7: PR を develop へ順次反映

開発は並列でも、merge は順次行う。

planned merge order の PR ごとに以下を行う。

1. CI status を確認する。
2. mergeability を確認する。
3. develop へ merge する。
4. orchestrator worktree を更新する。
5. integration verification を実行する。
6. verification が失敗した場合は merge line を止め、原因 Issue の fix workflow を開始する。

merge order の判断:

- 強い依存がある Issue を先にする。
- 共有基盤の大きな変更は、依存する UI / docs / test 変更より先にする。
- 独立している場合は conflict risk が低い PR を先にしてよい。
- ユーザー指定の `--merge-order` がある場合はそれを優先する。

#### PR merge method の用語メモ

GitHub の PR 反映には主に 3 種類ある。

| method | 何が起きるか | 向いている場合 |
| --- | --- | --- |
| merge commit | PR の commit 履歴を残したまま、merge commit を 1 つ作る | 複数 commit の経緯を残したい |
| squash merge | PR 内の commit を 1 commit にまとめて develop へ入れる | Issue 単位で履歴をきれいにしたい |
| rebase merge | PR の commit を develop の先頭へ直線的に積む | linear history を重視する |

この仕様では、初期既定は「リポジトリの GitHub 設定で許可・推奨されている方法に従う」とする。つまり、ユーザーが毎回 method を選ぶ必要はない。repository policy が決まっているならそれを使い、決まっていない場合だけ確認する。

### Phase 8: UAT と fix loop

`--full` が指定された場合、または Issue が実際の動作確認を必要とする場合は UAT を行う。

UAT では自動チェックに加えて、実機 / GUI 確認の手順生成まで含める。

UAT plan:

- Issue の受入条件から acceptance scenario を導出する。
- 可能な範囲で local functional check を実行する。
- GUI / 実機確認が必要な場合は、ユーザーが実施できる手順を生成する。
- 手順には、前提、操作手順、期待結果、確認観点、失敗時に保存すべき evidence を含める。
- 自動化できた結果と、手動確認が必要な項目を分けて記録する。

UAT artifact:

```text
workspace/management/runs/<run_id>/uat-report.md
```

UAT が失敗した場合:

1. failure を Issue / PR へ mapping する。
2. fix branch / worktree を reopen または create する。
3. focused failure prompt で CommandMate Codex session を起動する。
4. follow-up PR を作成する。
5. verification 後に merge する。
6. failed UAT scenario を再実行する。

retry limit:

- default 3
- product decision blocker の場合は早めに止める。

### Phase 9: 最終報告

最終報告に含めるもの:

- Issue list と final state
- PR list と merge result
- files changed summary
- verification commands と結果
- UAT status
- 実機 / GUI 確認手順と結果
- unresolved risks
- user action required

出力:

```text
workspace/management/runs/<run_id>/final-report.md
```

## 7. ユーザーとの対話方針

ハーネスはユーザー負担を最小化する。ただし、続行が危険な場合は必ず聞く。

ユーザーに聞く条件:

- Issue の受入条件が欠けており、推定もできない。
- 指定された複数 Issue が矛盾する挙動を要求している。
- product decision が不足している。
- 既存 worktree に未コミット変更がある。
- 破壊的操作または force-push が必要。
- UAT に、agent が操作できない実機 / GUI / 外部環境が必要。
- repository policy が不明で、PR merge method を選ぶ必要がある。

ユーザーに聞かない条件:

- 不足情報を test や既存コード pattern から推定できる。
- 曖昧さが実装内部だけに閉じている。
- 安全で保守的な default がある。
- failed verification に明確な local fix がある。

質問形式:

- 一度に最大 3 問。
- 具体的で短くする。
- default assumption がある場合は併記する。

## 8. CommandMate Adapter 要件

Codex ハーネスには `commandmatedev` の薄い adapter が必要。

必要な機能:

| 機能 | CommandMate 操作 |
| --- | --- |
| worktree / session 一覧 | `commandmatedev ls --json` |
| 起動 ping | `commandmatedev send <id> "hello"` |
| Codex task 送信 | `commandmatedev send <id> "<prompt>" --auto-yes --duration <duration>` |
| Codex agent 明示時の task 送信 | `commandmatedev send <id> "<prompt>" --agent <name> --auto-yes --duration <duration>` |
| wait / poll | `commandmatedev wait <id>` または API polling |
| 結果 capture | `commandmatedev capture <id> --json` |
| stuck worker retry | short resume prompt を送る |

設定値:

```text
codex_agent_name = null
default_duration = "3h"
startup_timeout_sec = 60
worker_timeout_sec = 10800
max_startup_retries = 1
```

`codex_agent_name = null` の場合は Anvil 側と同じく `--agent` を付けない。環境によって Codex 専用 agent 名が必要な場合のみ設定する。

## 9. 成果物と状態の配置

Management artifacts:

```text
workspace/management/
  codex_harness_spec.md
  runs/
    YYYYMMDD-HHMMSS-orchestrate/
      manifest.md
      issue-analysis.md
      dependency-plan.md
      worker-sessions.md
      merge-report.md
      uat-report.md
      final-report.md
```

各 worker worktree 内の成果物:

```text
dev-reports/issue-<number>/
  design.md
  implementation-summary.md
  verification.md
```

任意の PHOTON / eval artifacts:

```text
workspace/eval/runs/codex-orchestrate/<run_id>/
  manifest.md
  raw/
  analyzed/
  report.md
```

## 10. 安全ルール

- 既存 worktree を明示承認なしに削除・reset しない。
- harness が所有する branch の PR 更新に必要な場合を除き、force-push しない。
- CI が失敗している PR を、ユーザー承認なしに merge しない。
- develop verification が失敗したら、それ以降の merge を続けない。
- run artifact に raw secret や未 redaction の absolute user path を保存しない。
- Issue や worker が生成した破壊的 shell command は、承認なしに実行しない。
- 生成した temporary test は、Issue が commit 対象として明示していない限り tracked source 外に置く。

## 11. 品質ゲート

Issue ごとの最低条件:

- design note が存在する。
- implementation summary が存在する。
- focused verification が実行済み、または skip 理由が記録されている。
- PR が Issue に link している。
- PR body に tests run が記載されている。

merge の最低条件:

- CI pass、または明示的な waive がある。
- mergeable である。
- merge 後に develop が更新されている。
- integration verification が pass している。

最終完了の最低条件:

- 指定 Issue がすべて merged、理由付き skipped、または user-visible action 付き blocked のいずれかである。
- final report が存在する。
- UAT status が記録されている。
- 実機 / GUI 確認が必要な場合は、手順と期待結果が記録されている。

## 12. PHOTON Action Memory 連携

PHOTON 連携は有用だが、最初の orchestration loop では必須ではない。

初期用途:

- 各 Issue run の normalized event を記録する。
- worker startup failure、test failure、UAT failure を再利用可能な failure case として記録する。
- 成功した Issue completion を compact case として記録する。
- orchestration across runs の summary metrics を出す。

推奨 event kind:

```text
orchestrate.started
issue.analysis.completed
issue.enhancement.requested
issue.enhancement.applied_to_github
dependency.plan.completed
worker.started
worker.blocked
worker.completed
pr.created
pr.merged
verification.failed
uat.failed
uat.passed
orchestrate.completed
```

PHOTON failure は fail-open にする。

- event logging に失敗したら、run manifest に warning を書いて続行する。
- suggestion / ranking が使えなければ deterministic planning を使う。

## 13. 残課題の解決方針

Issue 2, 3, 4, 5 を対象にした dry-run / worktree manager テストでは、planning、実 worktree 作成、CommandMate 送信コマンド生成、UAT 手順生成までは確認できた。一方で、完全な `/orchestrate` 運用にするには次の課題を段階的に解消する必要がある。

### 13.1 CommandMate 実送信後の processing 監視

Anvil 側の `/orchestrate` では、worker 起動後に `processing` 状態を必ず確認し、処理していない worker へ resume message を送る運用になっている。Codex 版でも同じ考え方を採用する。

方針:

1. `commandmatedev send <worktree-id> "hello"` を送信する。
2. `commandmatedev ls --json` または CommandMate API で session running / ready を確認する。
3. Codex task prompt を送信する。
4. 10-30 秒待って processing 状態を確認する。
5. `running=true` かつ `processing=false` の場合は短い resume message を 1 回だけ送る。
6. それでも processing にならない場合は worker を `blocked` として `worker-sessions.md` に記録し、ユーザーへ報告する。

resume message は原則として短い継続指示に留める。ただし、task prompt 自体が処理されていない可能性が高い場合は、直接の日本語指示に切り替えず、同じ Codex skill / prompt を再送信する。

完了条件:

- worker ごとに `sent`, `processing`, `completed`, `blocked`, `timeout` の状態を記録できる。
- processing 監視に失敗しても orchestrator 全体は落とさず、該当 worker だけを blocked にできる。
- capture 結果または dev-reports が存在しない worker を成功扱いにしない。

### 13.2 PR 作成と merge pipeline の実運用化

現状は PR body / report 生成と dry-run merge の入口が中心である。実運用では、PR 作成、CI 確認、mergeability 判定、develop 更新、integration verification を 1 本の順次 pipeline として扱う。

方針:

1. 各 worktree で `develop..HEAD` の commit があることを確認する。
2. dirty worktree のまま PR 作成しない。未コミット変更がある場合は worker に commit させるか blocked にする。
3. PR は `develop` 向けに作成し、Issue link、tests run、known risks、orchestration run ID を body に含める。
4. merge 前に CI status と GitHub の mergeability を確認する。
5. merge method は repository default を優先する。method 選択が必要な場合だけユーザーへ確認する。
6. merge 後は orchestrator worktree で `git fetch origin develop` / `git pull --ff-only origin develop` 相当を行う。
7. 設定された integration verification command を実行する。
8. verification が失敗したら以降の merge を止め、原因 Issue の fix workflow に移る。

完了条件:

- `pr-report.md` に PR number / URL / status / blocked reason が残る。
- `merge-report.md` に CI status、mergeability、merge result、develop verification result が残る。
- CI failure または merge conflict を成功扱いにしない。

### 13.3 Issue 詳細化結果の GitHub Issue 本文反映

ユーザー方針として、Issue 詳細化の結果は GitHub Issue 本文へ反映する。Codex 版では過剰レビューを避けるため、反映対象は実装安全性に必要な不足情報に限定する。

方針:

1. Issue 本文から目的、受入条件、影響範囲、非ゴール、テスト期待値を抽出する。
2. 受入条件が十分なら反映しない。
3. 不足がある場合はユーザーに最大 3 問だけ確認する。
4. 回答後、Issue 本文の末尾に `## Orchestration Notes` を追加または更新する。
5. dry-run では GitHub へ書き込まず、本文差分だけを `issue-analysis.md` に出す。

反映する情報:

- 明確化された受入条件
- 実装上の制約
- 影響ファイル / module
- 明示された非ゴール
- UAT / 実機確認が必要な観点

完了条件:

- `gh issue edit` または GitHub plugin で Issue 本文を更新できる。
- 更新前後の差分が run artifact に残る。
- 既存本文を破壊せず、ハーネス管理セクションだけを idempotent に更新できる。

### 13.4 UAT failure fix loop

現状は UAT failure 用 follow-up prompt 生成までで、fix branch / worktree 作成は未完である。Anvil 側の `/uat-fix-loop` 相当として、失敗 scenario を該当 Issue / PR / file に mapping し、focused fix を回す。

方針:

1. `uat-report.md` または `uat-failures.json` から fail scenario を読み込む。
2. failure を Issue number、PR number、推定 file、受入条件へ mapping する。
3. `fix/issue-<number>-uat-<slug>` branch / worktree を作成または再利用する。
4. focused failure prompt を Codex worker へ送る。
5. focused verification と failed UAT scenario の再実行結果を記録する。
6. follow-up PR を作成し、merge pipeline に戻す。

retry limit:

- default 3
- 同じ scenario が 2 回連続で失敗し、原因が product decision の場合はユーザー判断へ回す。
- 外部環境や実機操作が必要で agent が検証できない場合は、manual evidence request として止める。

完了条件:

- UAT failure から fix worktree を自動作成できる。
- retry 回数、修正 PR、再 UAT 結果が `uat-report.md` と `final-report.md` に残る。

### 13.5 依存関係推定と並列化精度

Issue 2, 3, 4, 5 のテストでは安全寄りに `#2 -> #3 -> #4 -> #5` の直列計画になった。初期実装としては許容できるが、実運用では schema と sanitizer のように並列化できる可能性があるものを識別する必要がある。

方針:

1. Issue 本文の path 抽出に加え、`rg` による repository inspection を行う。
2. title / body / acceptance criteria から key phrase を抽出し、関連 file を候補に追加する。
3. 候補 file を repository local path、外部参照 path、documentation path に分類する。
4. 同一 file / 同一 package / API contract / storage schema / test fixture の重なりから conflict risk を算出する。
5. direct dependency がある場合だけ直列にする。
6. 判断が弱い場合は weak-conflict とし、並列実行後の設計突合バリアで確認する。

Issue 2, 3, 4, 5 の期待例:

- Issue 2: schema 基盤。Issue 4 / 5 の前提になりやすい。
- Issue 3: sanitizer。Issue 4 の保存前処理に関係するが、schema 定義とは並列化できる可能性がある。
- Issue 4: SQLite event store。Issue 2 / 3 の成果に依存しやすい。
- Issue 5: sidecar API。Issue 2 / 4 の成果に依存しやすい。

推奨 batch:

```text
Batch 1: #2, #3
Batch 2: #4
Batch 3: #5
```

ただし、Issue 2 が `EventRecord` の contract を大きく変える場合は、Issue 3 は並列可、Issue 4 / 5 は Issue 2 後に開始する。

完了条件:

- `dependency-plan.md` に dependency reason が明記される。
- conservative default だけで全 Issue を直列化しない。
- 直列化する場合は、どの成果物がどの Issue の入力になるかを説明できる。

### 13.6 推定影響ファイルの品質改善

Issue 本文に外部 repo の参照 path や absolute path が含まれる場合、worker の suspected files に混ざると実装対象を誤る。Issue 2-5 テストでは objective 見出しの抽出と absolute path 断片の抑制を改善したが、さらに repository inspection を加える。

方針:

1. Issue 本文から抽出した path は、repo 内に存在するか確認する。
2. 存在しない path は `external reference` として分離し、suspected files には入れない。
3. absolute user path は artifact に raw 保存しない。必要なら redacted path として扱う。
4. `rg` 結果は上位件数を制限し、noise が多い key phrase は捨てる。
5. worker prompt には、実装対象 file と参考情報を分けて渡す。

完了条件:

- `issue-analysis.md` に `推定影響ファイル` と `参考情報` が分かれて出る。
- `/Users/...`、`/home/...`、`/tmp/...` の raw path が artifact に残らない。
- 存在しない file を primary target として扱わない。

### 13.7 PHOTON Action Memory event 連携

PHOTON 連携は初期 loop の blocker ではない。安定した orchestration が先であり、event emission は fail-open の sidecar 連携として追加する。

方針:

1. run artifact を canonical record とする。
2. PHOTON 側には normalized event を best-effort で送る。
3. sidecar が不在、timeout、error の場合は manifest に warning を残して続行する。
4. worker startup failure、verification failure、UAT failure は再利用可能な failure case として保存する。
5. successful Issue completion は compact case として保存する。

完了条件:

- event emission failure で `/orchestrate` が止まらない。
- event payload に raw secret / raw absolute user path が入らない。
- run artifact と PHOTON event の対応 ID を追跡できる。

### 13.8 CommandMate UI 上の Codex カスタムコマンド確認

repository local の `.codex/skills` / `.codex/prompts` は CommandMate で都度読み込みされる。実運用前に、対象 worktree で候補表示されることを確認する。

確認項目:

- `/.codex/skills/orchestrate/SKILL.md` が `/orchestrate` として候補に出る。
- `/.codex/skills/codex-issue-worker/SKILL.md` が `/codex-issue-worker` として候補に出る。
- `/.codex/prompts/orchestrate-worker.md` が `/prompts:orchestrate-worker` として候補に出る。
- 追加後に worktree 画面を開き直す、または再取得すると反映される。
- Claude 用 `.claude/commands` と Codex 用 `.codex` が混ざって候補表示されない。

完了条件:

- CommandMate UI で Codex 用候補が確認済みである。
- UI 確認結果を `worker-sessions.md` または `final-report.md` に残す。

## 14. 初期実装計画

1. `workspace/management/templates/` に prompt / report template を追加する。
2. `scripts/codex_orchestrate.py` のような小さな command runner を追加し、まず dry-run planning を実装する。
3. Issue fetch と軽量 analysis を実装する。
4. 必要な場合に GitHub Issue 本文へ詳細化結果を反映する。
5. dependency planning と worktree name generation を実装する。
6. `--agent` 省略を既定にした CommandMate adapter を実装する。
7. worker prompt dispatch と polling を実装する。
8. PR collection と merge planning を実装する。
9. 実機 / GUI 確認手順を含む UAT report template を追加する。
10. optional PHOTON event emission を追加する。

## 15. 決定済み事項と残論点

### 決定済み

| 項目 | 方針 |
| --- | --- |
| CommandMate agent 指定 | Anvil 側と同じく通常 worker では `--agent` を指定しない。必要な環境だけ設定で明示する |
| develop 取得元 | `origin/develop` |
| Issue 詳細化の反映先 | 不足修正は GitHub Issue 本文へ反映する |
| UAT | 自動チェックに加え、実機 / GUI 確認の手順生成まで含める |
| PHOTON 連携 | 初期 loop では任意。失敗しても orchestration は止めない |

### 残論点

| 項目 | 現時点の扱い |
| --- | --- |
| PR merge method | 初期既定は repository default。repository policy が不明、または複数 method が許可されていて選択が必要な場合だけユーザーへ確認する |
| UAT の実機 evidence | スクリーンショット、ログ、操作動画など、どの evidence を標準にするかは対象 product ごとに決める |
