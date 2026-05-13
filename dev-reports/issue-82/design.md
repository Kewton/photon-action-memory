# Design Note - Issue #82: `/v1/summarize` API contract と schema

## Objective

`/v1/summarize` の **API contract と schema** を v0.4.0 P0 として固定する。
Anvil の beta + gamma-light 評価で観測された seed の scenario 依存挙動
(S3-01 / S5-01 改善 ↔ S2-03 で seed-induced premature termination で退化)
に対する制御余地を後段で扱えるよう、まずは Anvil が turn 終了時に送る
ための request schema を厳密に型付けする。

このイシューでは endpoint の **実装本体は対象外** で、schema 検証と
fail-open レスポンスのみを用意する。

## Scope

- `photon_action_memory/api/schema_v2.py` に
  - `SummarizePolicy`
  - `SummarizeRequest`
  - `SummarizeResponse`
  - `SummarySource` (chunk / evidence references)
  を追加し、`__all__` に export する。
- `photon_action_memory/api/server.py` の `/v1/summarize` を
  - empty payload → 422 (FastAPI/pydantic validation)
  - 最小 valid payload → 200 で `not_implemented` ステータスを返す
  に置き換える。
- `tests/test_schema_v2.py` に request/response の round-trip と
  欠落フィールド validation テストを追加。
- `tests/test_sidecar_api.py` の summarize テストを 422 / 200 path に更新。

## Design

### `SummarizeRequest`

| field | 必須 | 型 | 目的 |
|---|---|---|---|
| `schema_version` | yes | `SchemaVersionV2` (`"action-memory.v0.2"`) | 既存 v0.2 schema と同一の version literal を使う。v0.4.0 は schema 互換性を維持するため major bump しない。 |
| `request_id` | yes | `str` | リクエスト追跡 |
| `session_id` | optional | `str` | Anvil session キー |
| `turn_id` | optional | `str` | turn 終了時の turn 識別子 |
| `agent` | optional | `AgentInfo` | Anvil の `name`/`version` (ContextPack と同じ型を再利用) |
| `repo` | optional | `RepoInfo` | repo root / commit 情報 (ContextPack と同じ型を再利用) |
| `task` | optional | `TaskState` | turn の user_request / mode (ContextPack と同じ型を再利用) |
| `summary_level` | optional, default `"turn"` | `SummaryLevel` | `chunk`/`turn`/`session`/`case` |
| `chunk_ids` | optional, default `[]` | `list[str]` | 集約対象の ActionChunk ID |
| `recent_event_ids` | optional, default `[]` | `list[str]` | 集約対象の raw event ID (補助) |
| `parent_summary_ids` | optional, default `[]` | `list[str]` | 階層的な要約 (turn を session に合成する等) |
| `policy` | optional | `SummarizePolicy` | 要約方針 (下記) |

### `SummarizePolicy`

`workspace/v0.2.0/03_schema_and_api.md` で先行スケッチされていた policy
を schema 化する。Anvil が seed 由来の premature termination を緩和する
ため、後段で `allow_termination_when_unresolved` 等のフラグを追加できる
よう `extra="allow"` を維持する。

| field | default | 目的 |
|---|---|---|
| `require_evidence_ids` | `True` | facts / hypotheses に `evidence_ids` を要求する |
| `separate_fact_and_hypothesis` | `True` | ActionSummary の facts / hypotheses を分離する |
| `include_failed_attempts` | `True` | failed_attempts を残す |
| `include_avoid_guidance` | `True` | avoid をエクスポートする |
| `max_summary_chars` | `4000` (ge=0) | 要約全体の概算上限 |
| `max_facts` | `16` (ge=0) | facts の最大件数 |
| `max_hypotheses` | `8` (ge=0) | hypotheses の最大件数 |

### `SummarizeResponse`

| field | 必須 | 型 | 目的 |
|---|---|---|---|
| `schema_version` | yes | `SchemaVersionV2` | リクエストと一致 |
| `request_id` | yes | `str` | リクエスト追跡 |
| `model_version` | yes | `str` | 生成側モデル / fallback identifier |
| `sidecar_status` | yes | `str` | `ok` / `not_implemented` / `fail-open` 等 |
| `summary` | optional | `ActionSummary | None` | v0.2 schema の ActionSummary をそのまま返す |
| `validation` | optional | `SummaryValidationResult | None` | `/v1/summary/validate` と同じ型を再利用 |
| `warnings` | optional | `list[ContextPackWarning]` | sidecar 由来の non-fatal 警告 (ContextPack と統一) |

### `/v1/summarize` endpoint

- pydantic が `SummarizeRequest` を解釈するので、空 payload は schema 違反で 422。
- 本体実装はまだ無いため、validated request を受け取った後は
  `SummarizeResponse(... model_version=FALLBACK_MODEL_VERSION,
  sidecar_status="not_implemented", summary=None,
  warnings=[ContextPackWarning(kind="not_implemented", message=...)])`
  を 200 で返す。これにより contract は確定し、後続 P0/P1 イシューで
  本体 (生成 + validation 連携) を埋められる。

## 既存 schema との整合性

- `schema_version` literal は v0.2 と同一 (`"action-memory.v0.2"`)。
  v0.4.0 では schema 構造のみ追加し、既存 endpoint との後方互換を維持。
- `AgentInfo`, `RepoInfo`, `TaskState` は v1 schema から既に v0.2
  request 群で再利用済みなので踏襲する。
- response の `summary` は `ActionSummary`、`validation` は
  `SummaryValidationResult` をそのまま再利用 → `/v1/summary/upsert` /
  `/v1/summary/validate` とフォーマット互換。
- `warnings` は `ContextPackWarning` を再利用し、`/v1/context/pack` /
  `/v1/evaluate` と統一されたエラーモデルにする。
- `SummarizePolicy.max_*` は ge=0 のみ強制し、`extra="allow"` で将来の
  termination 制御フラグを破壊変更なしで追加できる。

## Safety Notes

- 既存 `test_summarize_is_m2_stub` (501 を期待) は今回の contract 化で
  挙動が変わるため、422 (empty) / 200 (minimum valid) 用にリライトする。
- 生成本体は別 issue に切り出すため、`summary=None` のレスポンスを
  返したときに Anvil 側で fail-open できることを `warnings` で明示する。
