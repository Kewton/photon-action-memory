# Issue #98 — Implementation Summary

## 変更概要

Anvil expanded eval 用の photon-memory seed 8 件すべてに `lang=en/ja` の
バリアントを併記し、Anvil の日本語タスクと photon が返す ContextPack の
言語ギャップを解消した。token budget (800) に収まり、`extra="allow"`
スキーマのおかげで既存パーサに対し後方互換。

## 追加 / 変更ファイル

新規 seed (multilingual):
- `tests/fixtures/shared/anvil_eval_s1_02_action_summary.json`
- `tests/fixtures/shared/anvil_eval_s2_03_action_summary.json`
- `tests/fixtures/shared/anvil_eval_s3_01_action_summary.json`
- `tests/fixtures/shared/anvil_eval_s3_03_action_summary.json`
- `tests/fixtures/shared/anvil_eval_s3_04_action_summary.json`
- `tests/fixtures/shared/anvil_eval_s5_01_action_summary.json`
- `tests/fixtures/shared/anvil_eval_s6_04_action_summary.json`
- `tests/fixtures/shared/anvil_eval_sp01_action_summary.json`

新規スクリプト:
- `scripts/seed_expanded_eval_scenarios.sh` (8 fixtures を `/v1/summary/upsert`
  にバッチ投入)

新規テスト:
- `tests/test_anvil_eval_multilingual_seeds.py` (34 ケース)

ドキュメント:
- `dev-reports/issue-98/design.md`
- `dev-reports/issue-98/implementation-summary.md` (本ファイル)
- `dev-reports/issue-98/verification.md`

## seed の構造

各 seed の `facts` / `next_hints` (+ 該当する場合は `avoid`) に EN/JA の
2 件ペアを格納。同じ `evidence_ids` と `confidence` を共有し、同一根拠の
言語別表現として扱う。

```json
"facts": [
  { "text": "Repo S3-01 has a bug in calculator.py: the add() ...",
    "evidence_ids": ["anvil-eval-s3-01-ev-001"], "confidence": 0.99, "lang": "en" },
  { "text": "リポジトリ S3-01 の calculator.py にバグがある。add() が ...",
    "evidence_ids": ["anvil-eval-s3-01-ev-001"], "confidence": 0.99, "lang": "ja" }
]
```

`lang` は `Fact` / `NextHint` / `AvoidGuidance` の正式フィールドではないが、
`SidecarModel.extra="allow"` により無害に保持される。`render_summary` は
`facts` / `next_hints` / `avoid` の各要素を順に並べて prompt-visible text に
出力するため、EN/JA の両エントリがそのまま FACT: / HINT: / AVOID: 行として
ContextPack に現れる。

## token budget の収まり方

`ContextPackBudget.max_memory_tokens` のデフォルト 800 token に対し、
各 seed の rendered text 推定値は 62〜238 token (Bilingual 化後)。各 seed の
`token_cost.estimated_summary_tokens` を実際の rendered token 数に合わせて
更新済み。個別 seed はすべて単独で 800 token cap に収まる。

`tests/test_anvil_eval_multilingual_seeds.py::test_seed_fits_default_context_pack_budget`
で個別 seed が admit されることを、
`test_all_seeds_fit_combined_default_budget` で 800 token cap が破られない
ことを検証している。

## 後方互換性

- `lang` は extra field なので photon / Anvil の既存 parser は無視するだけ
  で壊れない。
- `token_cost.tokens_saved_vs_raw` は引き続き正の値を維持。
- 既存 902 件のテストはすべて pass。
