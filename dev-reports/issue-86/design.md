# Design Note — Issue #86: v0.4.0 P1 — `/v1/summarize` evidence grounding + raw firewall

## Objective

Action Context Firewall として、prompt-visible memory は evidence-grounded summary だけに限定する。`/v1/summarize` は agent から raw tool / action 履歴を含む候補 ActionSummary を受け取るため、その出口で raw stdout/stderr/secret が prompt-visible なフィールド (`facts[*].text` 等) に混入しないことを保証する必要がある。

## Scope

このイシューでカバーする変更:

- `/v1/summarize` (現状 501 stub) を **summary firewall** エンドポイントとして実装する。
- raw 出力検出を `SummaryFidelityChecker` に追加し、`/v1/summary/validate` でも同じシグナルを得られるようにする。
- `/v1/summarize` レスポンスに `validation_results`, `admission_decisions`, `omitted`, `evidence_ids_referenced` を含めて `/v1/evidence/expand` と連携可能にする。
- 既存 `/v1/context/pack` の raw policy 実装 (`evaluate_raw_item`, `has_sensitive_content`) を再利用し、二重実装を避ける。

スコープ外:

- LLM を呼び出して draft summary を生成する処理。`/v1/summarize` はあくまで agent が組み立てた draft の **firewall + validation** に専念する。
- summary store への upsert (これは `/v1/summary/upsert` の責務)。

## Acceptance Criteria → 実装マッピング

| AC | 実装ポイント |
|----|-------------|
| `/v1/summarize` 生成 summary の prompt-visible fact は evidence_ids を持つ | `SummaryFidelityChecker` の既存 `missing_evidence_id` チェックを `/v1/summarize` 内でも走らせ、`validation_results` に反映 |
| raw stdout/stderr/secret は `ContextPack.items[].text` に入らない | `/v1/summarize` 段階で fact text を `sanitize_text_with_report` で redact。raw_evidence は `evaluate_raw_item` で deny して `admission_decisions` に記録。これにより後段の `/v1/context/pack` まで raw が流れない |
| `validation_results` で grounding / raw leakage の状態を確認できる | `SummaryValidationResult` を返す。grounding 系の既存 issue 種に加え、新 issue 種 `raw_output_in_field` を追加 |
| `/v1/evidence/expand` と連携し、必要時だけ redacted snippet を返せる | `/v1/summarize` のレスポンスに `evidence_ids_referenced: list[str]` を含め、agent が必要時に `/v1/evidence/expand` を呼び出せるようにする。expand 側の redaction は既存 (`policy.redact_again`) を再利用 |

## API 設計

### Request — `POST /v1/summarize`

```jsonc
{
  "schema_version": "action-memory.v0.2",
  "request_id": "req-...",
  "draft_summary": {ActionSummary},
  "evidence_records": [ {evidence_id, kind, summary, content?, ...}, ... ],
  "raw_evidence": [ {item_id, kind, content, source?}, ... ]
}
```

- `draft_summary` は agent が組み立てた候補。`facts/hypotheses/...` は構造化されている前提。
- `evidence_records` は grounding 用 (`SummaryFidelityChecker` に渡す)。
- `raw_evidence` は raw tool log。`/v1/context/pack` と同様に default-deny。

### Response

```jsonc
{
  "schema_version": "action-memory.v0.2",
  "request_id": "req-...",
  "summary": {ActionSummary},          // firewalled: secrets redacted in prompt-visible fields
  "validation_results": [ {SummaryValidationResult} ],
  "admission_decisions": [ {ContextAdmissionDecision}, ... ],  // raw_evidence deny entries
  "omitted": [ {OmittedItem}, ... ],   // raw_evidence omitted with reason
  "evidence_ids_referenced": ["ev-001", ...]
}
```

## SummaryFidelityChecker 拡張

- 新 issue 種 `raw_output_in_field` を追加 (blocking)。
- 検出対象: `facts[*].text`, `hypotheses[*].text`, `failed_attempts[*].action / outcome`, `avoid[*].action / reason`, `actions_done[*].target / command / outcome`, `next_hints[*].target / reason`, `validity.reason`。
- 検出ロジック: `photon_action_memory.context.raw_policy.has_sensitive_content` を再利用 (DRY)。

## Firewall (redaction) ロジック

`/v1/summarize` 内で `_apply_summary_firewall(summary) -> ActionSummary` ヘルパーを置く:

- 各 prompt-visible 文字列に対し `sanitize_text_with_report` を適用。
- redact が発生した場合は元のオブジェクトを `model_copy(update=...)` で差し替えて新しい `ActionSummary` を返す。
- 該当した検出は `validation_results` に `raw_output_in_field` issue として残す。

## エラーポリシー / fail-open

- 内部例外時は `summary` をそのまま返し、`validation_results` に `kind="summarize_error"` の issue を 1 件積む (status=200, fail-open)。これは `/v1/summary/validate` の既存 fail-open と一貫。
- raw_evidence は例外時でも default-deny。

## Safety Notes

- prompt-visible 文字列を redact してから validation を実行する順序にする。これにより `raw_output_in_field` 検出は redact 前の draft に基づき report され、返却される summary は redact 後の安全な値になる。
- 既存の `_BLOCKING_KINDS` に `raw_output_in_field` を含めて status=invalid に倒す。
- `evidence_ids_referenced` は `facts/hypotheses/failed_attempts/avoid/actions_done` の `evidence_ids` を union したもの。順序は安定化させる (set→sorted)。

## Touched files (見込み)

- `photon_action_memory/api/schema_v2.py`: 新 `SummarizeRequest`, `SummarizeResponse` 定義。
- `photon_action_memory/api/server.py`: `summarize_stub` を実装に差し替え。
- `photon_action_memory/eval/summary_fidelity.py`: `raw_output_in_field` 検出を追加。
- `photon_action_memory/eval/__init__.py`: 必要なら export 追加 (今のところ不要)。
- `tests/test_summary_fidelity.py`: 新検出のユニットテスト。
- `tests/test_raw_tool_log_policy.py`: `/v1/summarize` の raw firewall 統合テスト。
