# photon-action-memory Live Injection Sidecar Runbook

作成日: 2026-05-09

## 対象

Anvil live injection / canary 検証で使う photon-action-memory sidecar の準備手順。

この runbook は photon-action-memory 側だけを対象にする。Anvil 側の prompt 注入実装、LLM 実行、canary rollout 判定は別タスク。

## 方針

`/v1/context/pack` の summary 解決は次の順序で行う。

1. `candidate_summary_ids` がある場合は、その明示候補だけを解決する。
2. `candidate_summary_ids` が空の場合は、`repo.name` で stored summary を検索する。
3. `repo.name` が空の場合は、`repo.root` の basename を repo key として使う。
4. `task.task_signature` が request に含まれる場合は、まず `repo_id + task_signature` で検索する。
5. repo をまたぐ global fallback は行わない。

この方針により、live injection で別 repo の memory が prompt に混入するリスクを避ける。

## Sidecar 起動

```bash
PHOTON_ACTION_MEMORY_DB=/tmp/photon-action-memory-v030-live-events.sqlite \
PHOTON_ACTION_MEMORY_SUMMARY_DB=/tmp/photon-action-memory-v030-live-summaries.sqlite \
python -m uvicorn photon_action_memory.api.server:app --host 127.0.0.1 --port 18765
```

port 3000 は使わない。

## Seed summary 投入

```bash
scripts/seed_live_injection_summary.py --url http://127.0.0.1:18765
```

投入される fixture:

- `tests/fixtures/shared/anvil_live_action_summary.json`

dry run:

```bash
scripts/seed_live_injection_summary.py --dry-run
```

## Context pack smoke

```bash
curl -sS http://127.0.0.1:18765/v1/context/pack \
  -H 'Content-Type: application/json' \
  --data @tests/fixtures/shared/anvil_live_context_pack_request.json
```

期待する結果:

- HTTP 200
- `sidecar_status=ok`
- `context_pack.repo_id=anvil-live-fixture`
- `context_pack.items[0].id=anvil-live-codename-001`
- `context_pack.items[0].text` に `heliograph` が含まれる
- `admission_decisions[0].decision=admit`

## Anvil 側に渡す確認ポイント

Anvil live injection 側では、上記 context pack response を prompt renderer が扱える必要がある。

重要な response shape:

```json
{
  "context_pack": {
    "mode": "summary_only",
    "items": [
      {
        "kind": "action_summary",
        "id": "anvil-live-codename-001",
        "text": "FACT: The project codename for repo anvil-live-fixture is heliograph."
      }
    ]
  }
}
```

Anvil 側 renderer が legacy の `kind=summary` / `summary` だけを見ている場合は、この v0.2 shape に対応する必要がある。

## Safety regression

photon-action-memory 側で維持すること:

- raw stdout/stderr/build_log は `context_pack.items` に入れない。
- stale/contradicted summary は検索後に除外する。
- empty summary は admission で omit し、`context_pack.omitted` に理由を残す。
- admitted summary は `admission_decisions` に `decision=admit` と `estimated_tokens` を残す。
- repo が特定できない request では stored summary を自動検索しない。

## 関連ファイル

- `photon_action_memory/api/server.py`
- `photon_action_memory/memory/retrieval.py`
- `tests/test_context_pack.py`
- `tests/test_anvil_context_pack_api.py`
- `tests/fixtures/shared/anvil_live_action_summary.json`
- `tests/fixtures/shared/anvil_live_context_pack_request.json`
- `tests/fixtures/shared/anvil_live_context_pack_response.json`
- `scripts/seed_live_injection_summary.py`
