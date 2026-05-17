# Action Memory LLM / PHOTON 改善計画

## 目的

v0.4.0 の目的は、現在の安全な rule-based 圧縮を維持したまま、任意機能として
LLM と PHOTON/MLX の改善余地を追加すること。

現在の baseline は次の決定的な変換である。

```text
event log -> ActionChunk -> ActionSummary
```

この方式は速く、再現性があり、MLX やモデル checkpoint がなくても動く。一方で、
test failure、diff、command output、複数 topic の意味までは深く読めない。
v0.4.0 では rule-based を fail-open baseline として残し、LLM / PHOTON は
opt-in の品質改善レイヤとして扱う。

## 現在の実装状態

| 領域 | 状態 |
|---|---|
| `/v1/summarize` | 実装済み。stored chunk、inline chunk、draft summary firewall に対応。 |
| default summary | `RuleBasedSummaryGenerator`。既存 `ActionSummaryBuilder` と同じ決定的経路。 |
| LLM draft summary | `PHOTON_SUMMARY_GENERATOR=llm` のときだけ有効。MLX は lazy import。 |
| LLM fallback | default は `rule_based`。`abort` は明示設定時のみ。 |
| response telemetry | `generator_used` / `generator_fallback_reason` を返す。 |
| PHOTON scorer | `ActionMemoryPhotonScorer` 境界と checkpoint loader は実装済み。 |
| checkpoint fixture | tiny fixture を `tests/fixtures/photon/checkpoints/action_memory_tiny/` に配置済み。 |
| live context ranking | `/v1/context/pack` はまだ deterministic/feedback-adjusted。PHOTON checkpoint の live wiring は未実装。 |

## LLM Draft Summary

LLM は source of truth ではなく、draft generator として使う。

```text
sanitized events
  -> deterministic ActionChunk grouping
  -> LLM draft ActionSummary JSON
  -> schema validation
  -> evidence grounding / raw leak / answer leak / fidelity gates
  -> SummaryStore
```

LLM に任せてよいこと:

- turn 内の evidence を簡潔な `facts[]` に変換する。
- 不確かな観察を `hypotheses[]` に分離する。
- 失敗した command / test を `failed_attempts[]` に整理する。
- 繰り返し失敗や irrelevant search を `avoid[]` に反映する。
- 次に読む file、実行する test、確認する symbol を `next_hints[]` にする。

LLM に任せないこと:

- 存在しない file、symbol、test、evidence ID を作る。
- raw stdout/stderr、secret、home path、stack dump を prompt-visible field に入れる。
- 不確かな主張を `facts[]` に入れる。
- agent が作業を終了すべきかを決める。

## LLM 設定

| Variable | Default | Meaning |
|---|---|---|
| `PHOTON_SUMMARY_GENERATOR` | `rule_based` | `llm` のときだけ LLM draft を試す。 |
| `PHOTON_SUMMARY_LLM_MODEL` | `mlx-community/Qwen2.5-7B-Instruct-4bit` | ローカル MLX model identifier/path。 |
| `PHOTON_SUMMARY_LLM_FALLBACK_POLICY` | `rule_based` | `rule_based` または `abort`。 |
| `PHOTON_SUMMARY_LLM_TEMPERATURE` | `0.1` | JSON 安定性重視の低温設定。 |
| `PHOTON_SUMMARY_LLM_MAX_TOKENS` | `512` | 生成 token 上限。 |
| `PHOTON_SUMMARY_LLM_SEED` | `1729` | deterministic seed。 |

失敗理由は closed enum として `generator_fallback_reason` に出す。prompt、
raw model output、raw exception body はログやレスポンスに出さない。

## PHOTON / MLX Scorer

PHOTON checkpoint は、文書回答を生成するためではなく、Action Memory の
summary / evidence / next action 候補を score/rank するために使う。

現在実装済みのもの:

- `PHOTON_ACTION_MEMORY_CHECKPOINT`
- `PHOTON_ACTION_MEMORY_CHECKPOINT_STRICT`
- checkpoint manifest/state/integrity loader
- `PhotonMLXActionMemoryScorer`
- checkpoint 欠落、破損、MLX 不在時の deterministic fallback
- tiny checkpoint による ranking difference test

checkpoint directory の形:

```text
checkpoint/
  manifest.json
  state.json
  weights.npz
  integrity.json
```

現時点の制約:

- committed fixture は CI 用の小さな動作確認 checkpoint であり、本番モデルではない。
- large checkpoint や model weights は git に入れない。
- `PHOTON_ACTION_MEMORY_CHECKPOINT` は scorer 境界の評価に使えるが、live
  `/v1/context/pack` ranking への接続は次の実装課題。

## PHOTON らしい効果として狙うこと

LLM draft は「意味のある ActionSummary を作る」ための改善で、PHOTON scorer は
「どの記憶を次の行動に効かせるか」を選ぶための改善である。

PHOTON checkpoint を live ranking に接続できると、次の効果を検証できる。

- lexical overlap だけでは拾えない類似作業の summary を上げる。
- 過去に成功した test / file / command の next hint を上げる。
- 失敗が繰り返された探索や command を下げる。
- evaluate feedback から、adopted / ignored / safety violation の傾向を ranking に反映する。
- context budget 内で、より行動に直結する memory を選ぶ。

## 段階導入

1. default は rule-based のままにする。
2. `PHOTON_SUMMARY_GENERATOR=llm` を shadow/eval で試す。
3. fallback reason、summary fidelity、answer-leak warning、tokens saved を見る。
4. eval/adoption log から checkpoint を作る。
5. checkpoint scorer の ranking difference を fixture と実ログで確認する。
6. `/v1/context/pack` ranking へ PHOTON scorer を注入する。
7. shadow mode で deterministic ranking と PHOTON ranking を比較する。
8. canary は raw leak、fail-open rate、latency が gate を満たした後に限定する。

## 検証

LLM draft summary:

```bash
python -m pytest \
  tests/test_summary_generator.py \
  tests/test_llm_draft_summary.py \
  tests/test_summarize_endpoint.py \
  -q
```

PHOTON checkpoint scorer:

```bash
python -m pytest \
  tests/test_action_memory_checkpoint_builder.py \
  tests/test_action_memory_scorer.py \
  tests/test_photon_adapter.py \
  tests/test_checkpoint.py \
  -q
```

sidecar contract:

```bash
python -m pytest \
  tests/test_anvil_contract.py \
  tests/test_anvil_context_pack_api.py \
  tests/test_anvil_evaluate.py \
  tests/test_summarize_endpoint.py \
  -q
```
