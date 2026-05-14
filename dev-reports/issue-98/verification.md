# Issue #98 — Verification

## 受け入れ基準とテスト対応

| 受け入れ基準 | 検証方法 | 結果 |
|---|---|---|
| 各 seed に `lang` field 付き日英バリアント記述 | `test_seed_has_en_and_ja_variants` (8 ケース) | PASS |
| context_pack response の text 出力で言語別 fact を併記 | `test_seed_rendered_text_contains_japanese` (8 ケース) — `render_summary` に EN/JA の `FACT:` / `HINT:` 行が並ぶことを確認 | PASS |
| token budget 内に収まること (800 token cap) | `test_seed_fits_default_context_pack_budget` (8 ケース) + `test_all_seeds_fit_combined_default_budget` | PASS |
| `seed_expanded_eval_scenarios.sh` で seed 化可能 | `test_seed_script_references_all_fixtures` + `bash -n` syntax 確認 | PASS |
| Anvil 側 (日本語タスク) で fact/hint の意味的一致が高まる | seed 内に JA 訳を併記。実 Anvil eval は別 issue で実行 (定性目標) | seed 整備完了 |

## 実行コマンドと結果

### Focused suite

```
python -m pytest tests/test_anvil_eval_multilingual_seeds.py -v
```
- 34 passed in 0.10s

### shared fixture / schema / context pack 横断

```
python -m pytest tests/test_shared_fixtures.py tests/test_anvil_eval_multilingual_seeds.py tests/test_schema_v2.py tests/test_context_pack.py
```
- 155 passed

### 全テストスイート

```
python -m pytest tests/
```
- 902 passed, 1 skipped (MLX smoke — opt-in)

### Seed script syntax

```
bash -n scripts/seed_expanded_eval_scenarios.sh
```
- syntax OK

## 数値根拠 (rendered token 推定)

| seed | estimated_summary_tokens | rendered≈ (`len(text)//4`) | 800 cap |
|---|---|---|---|
| anvil_eval_s1_02 | 112 | 111 | ✅ |
| anvil_eval_s2_03 | 210 | 209 | ✅ |
| anvil_eval_s3_01 | 134 | 132 | ✅ |
| anvil_eval_s3_03 | 238 | 237 | ✅ |
| anvil_eval_s3_04 | 168 | 168 | ✅ |
| anvil_eval_s5_01 | 202 | 201 | ✅ |
| anvil_eval_s6_04 | 212 | 211 | ✅ |
| anvil_eval_sp01  |  62 |  62 | ✅ |

すべての seed が単独で 800 token cap に余裕をもって収まる。

## 残課題 / 後続作業

- 実 Anvil eval (`e2e_uat_matrix.py` 等) で multilingual seed が retrieval 精度
  を実測で改善するかは別 issue で検証。本 issue では seed 整備と token budget
  整合性に範囲を限定。
