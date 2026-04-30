# MCP / stdio adapter design note

## 1. 目的

v0.1.0 の主経路は HTTP localhost sidecar である。一方で、Codex 系 agent や
editor / orchestration runtime からの統合では、HTTP を直接呼ぶより stdio や
MCP tool として公開する方が扱いやすい場合がある。

このメモは、将来の stdio / MCP adapter が既存 sidecar API schema を再利用し、
transport ごとに別 contract を増やさないための責務境界を固定する。

## 2. 基本方針

- `photon_action_memory.api.schema` の DTO を canonical schema とする。
- HTTP / stdio / MCP は transport adapter であり、action memory の business
  logic を持たない。
- adapter は transport 固有の envelope を canonical DTO に変換し、schema
  validation 後に core service へ渡す。
- `schema_version`、`request_id`、`session_id`、`sidecar_status`、warning
  形式は transport によらず同じ意味で扱う。
- Anvil や特定 agent の拡張情報は `agent` と `metadata` に閉じ込め、core
  schema を adapter 固有にしない。

## 3. 責務境界

### Core service

Core service は transport 非依存の処理を担当する。

- schema validation
- sanitizer
- event store append / read
- deterministic fallback ranking
- optional PHOTON scorer 呼び出し
- shadow evaluation record handling
- fail-open response shape の生成

### HTTP localhost sidecar

HTTP は v0.1.0 の唯一の実装対象 transport とする。

- `GET /health`
- `POST /v1/events`
- `POST /v1/suggest`
- `POST /v1/summarize`
- `POST /v1/evaluate`

HTTP layer は request / response の JSON encoding、status code、timeout、
local process health check を扱う。ranking、storage、redaction policy は
core service に委譲する。

### stdio adapter

stdio adapter は将来の local child-process integration 用 transport とする。

- stdin から request envelope を受け取り、stdout に response envelope を返す。
- payload body は HTTP endpoint と同じ canonical DTO を使う。
- adapter 固有 field は `method`、`id`、`payload` などの envelope に限定する。
- long-running session state や event store を adapter 内に持たない。
- stderr は diagnostics 専用にし、payload、secret、raw log を出さない。

stdio adapter の想定 mapping:

| stdio method | canonical DTO / operation |
| --- | --- |
| `health` | health response |
| `events.append` | `EventRequest` / `/v1/events` 相当 |
| `suggest` | `SuggestRequest` / `SuggestResponse` |
| `summarize` | summarize request / response contract |
| `evaluate` | `EvaluateRequest` / evaluation response contract |

### MCP adapter

MCP adapter は将来の tool / resource integration layer とする。

- MCP tool arguments を canonical DTO に変換する。
- MCP tool result は canonical response DTO を JSON として返す。
- MCP の tool description / capability discovery は adapter が担当する。
- suggestion、event persistence、ranking、sanitizer は core service に委譲する。
- raw session history や raw tool output を MCP resource として公開しない。

MCP tool の想定 mapping:

| MCP tool | canonical DTO / operation |
| --- | --- |
| `photon_health` | health response |
| `photon_record_event` | `EventRequest` / `/v1/events` 相当 |
| `photon_suggest` | `SuggestRequest` / `SuggestResponse` |
| `photon_summarize` | summarize request / response contract |
| `photon_evaluate` | `EvaluateRequest` / evaluation response contract |

## 4. Privacy / safety policy

adapter は secret や raw log を迂回路として渡してはならない。

- raw conversation log、prompt、tool stdout/stderr、command transcript をそのまま
  payload に入れない。
- API key、token、password、credential、署名付き URL、absolute user home path
  を raw のまま渡さない。
- adapter debug log に request / response payload 全体を出さない。
- validation error や transport error は raw payload を echo しない。
- 永続化前の sanitizer 適用は HTTP / stdio / MCP で同じ rule にする。
- adapter が受け取る `recent_events` は sanitized summary / artifact reference
  に限定する。

この方針により、HTTP を使わない統合経路でも event store、dataset exporter、
eval runner の privacy boundary を弱めない。

## 5. v0.1.0 で実装しない範囲

Issue #14 は design note のみを追加する。v0.1.0 では以下を実装しない。

- stdio adapter process
- MCP server
- MCP resource exposure
- adapter-specific schema
- adapter-specific event store
- remote MCP / remote sidecar deployment
- transport negotiation
- editor plugin integration
- raw log streaming
- secret passthrough mode
- adapter 経由の online training

v0.1.0 の実装優先度は、canonical schema、sanitizer、local HTTP sidecar、
deterministic fallback、shadow evaluation の順に維持する。

## 6. 将来の実装チェック

stdio / MCP 実装 issue では、最低限以下を確認する。

- HTTP fixture と同じ `SuggestRequest` / `SuggestResponse` が round-trip する。
- adapter envelope を外すと canonical DTO として validation できる。
- secret / absolute path / raw tool output が adapter log に残らない。
- sidecar unavailable 時も fail-open response shape を返す。
- adapter 側に ranking / storage logic が重複していない。
