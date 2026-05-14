# Issue #98 — Design Note

## Objective

`tests/fixtures/shared/anvil_eval_s*_action_summary.json` の seed は英語のみで
`facts` / `next_hints` / `avoid` を記述している。実シナリオの Anvil タスクは
日本語で task description を持つことが多いため、photon が返す
ContextPack の text と実タスクの言語が乖離し、retrieval / 指示理解の精度が
下がる。Issue #98 では各 seed に **日本語版を併記**し、prompt-visible text
で両言語が同時に出力されるようにする。

## Approach

ActionSummary の `Fact` / `NextHint` / `AvoidGuidance` は `SidecarModel`
(`extra="allow"`) を継承しているため、`lang` フィールドを追加してもスキーマ
互換性は保たれる。`render_summary` は既に `facts` / `next_hints` / `avoid`
全エントリを順に `FACT:` / `HINT:` / `AVOID:` プレフィックスで出力するため、
英語 / 日本語の 2 件を並べれば両言語が prompt 内に並ぶ。

### Seed JSON 構造

各 seed の `facts` / `next_hints` / `avoid` で、1 件の英語エントリと 1 件の
日本語エントリを併記する。`evidence_ids` と `confidence` は両言語で共有し、
同一の根拠を指す。

```json
"facts": [
  { "text": "Repo S1-02 ...", "evidence_ids": ["anvil-eval-s1-02-ev-001"],
    "confidence": 0.97, "lang": "en" },
  { "text": "リポジトリ S1-02 ...", "evidence_ids": ["anvil-eval-s1-02-ev-001"],
    "confidence": 0.97, "lang": "ja" }
]
```

`lang` の値は ISO-639-1 の `"en"` / `"ja"`。

### Token budget

- `ContextPackBudget.max_memory_tokens` のデフォルトは 800 token。
- 既存 EN-only seed は `estimated_summary_tokens` で 42〜58 token 程度。
- JA 併記後は概ね倍 (84〜120 token)。8 件の seed すべてを admit しても 800
  token 上限に余裕がある。
- 各 seed の `token_cost.estimated_summary_tokens` は実態に合わせて更新する。

### Seed script

`scripts/seed_expanded_eval_scenarios.sh` を一緒に取り込む。develop に存在する
版がそのまま使えるので、内容を変更せずに 8 件の fixture を `/v1/summary/upsert`
にバッチ投入する。

### 検証

新規テスト `tests/test_anvil_eval_multilingual_seeds.py` を追加し、

1. すべての seed が EN/JA の対をもつ (各 `facts` / `next_hints` / `avoid` で
   `lang` が両方の値を含む) ことを確認する。
2. 各 seed が `ActionSummary.model_validate` でロードでき、`render_summary` の
   出力に `FACT:` 行が `lang` 数だけ並ぶことを確認する。
3. `build_context_pack` を 800 token budget で実行し、全 seed が admit され、
   `token_budget.estimated_tokens` が 800 を超えないことを確認する。
4. `seed_expanded_eval_scenarios.sh` が 8 件分の fixture を参照していること。

## 想定影響

- Anvil 側 (日本語タスク) で retrieval された fact / hint の意味的一致が向上。
- 既存の英語タスクは EN エントリで従来どおり対応できる。
- スキーマ互換: `lang` は extra field なので photon / anvil 双方の既存 parser
  は無視するだけで壊れない。
