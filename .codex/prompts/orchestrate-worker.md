---
description: Worker prompt for a Codex issue worktree.
---

あなたは Issue 専用の git worktree で作業しています。

目的:
- 指定 Issue を、Issue 本文と orchestration notes に従って実装してください。

実施内容:
1. Issue summary と関連ファイルを読む。
2. 編集前に短い design note を `dev-reports/issue-<number>/design.md` に書く。
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
- `dev-reports/issue-<number>/implementation-summary.md`
- `dev-reports/issue-<number>/verification.md`
- 変更ファイル summary
- 実行した test と結果
- PR readiness status
- blocker があればその内容

