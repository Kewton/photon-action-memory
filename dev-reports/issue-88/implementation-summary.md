# Implementation Summary - Issue #88 (v0.4.0 P2)

## Changes

Added the procedure, runner, tests, and Anvil-facing docs needed to
reproduce the `/v1/summarize` integration smoke locally. The smoke covers
the full turn lifecycle: `summarize → summary/upsert → context/pack →
optional evidence/expand → evaluate`. While `/v1/summarize` is still the
M2 501 stub (P1 lives on Issue #86), the runner records
`status=summarize_stub` and continues from `/v1/summary/upsert` so the
rest of the lifecycle is verified today.

### New files

- `scripts/anvil_v1_summarize_smoke.py`
  - End-to-end smoke runner.
  - Drives `127.0.0.1:18765` (refuses any URL containing `3000`).
  - Three scenarios (`S2-03`, `S3-01`, `S5-01`) wired to assertions:
    - `regression-clear` / `regression-detected` for S2-03 (avoid survives).
    - `effect-present` / `effect-missing` for S3-01 / S5-01 (next_hints surface).
  - Exit code 1 if any scenario hits `regression-detected`, `effect-missing`, or `error`.

- `tests/test_anvil_v1_summarize_smoke.py`
  - 501-stub path (current branch).
  - 200 path with a stubbed `/v1/summarize` (post-P1).
  - Regression-detection check (S2-03 with `avoid` stripped).
  - Port-3000 rejection check.

- `workspace/v0.3.0/anvil-eval-beta-gamma-light-result.md`
  - Lightweight 3-scenario eval template covering the β (regression) and γ (effect) families.
  - Records sidecar startup command, smoke invocation, and result table per run.

- `dev-reports/issue-88/{design,implementation-summary,verification}.md`

### Updated docs

- `docs/photon-action-memory.md`
  - Added `/v1/summarize` smoke section with request envelope, expected
    response, and the runner command.

- `docs/anvil-integration.md`
  - Added `/v1/summarize` row to the API contract table.
  - Added Anvil-side request fields table.
  - Added the explicit turn-lifecycle timing diagram.
  - Updated the required call sequence to include `summarize → summary/upsert`.

## Acceptance Criteria Mapping

| Criterion | Status |
|---|---|
| local sidecar で `/v1/summarize` integration smoke を再現できる | Done. `scripts/anvil_v1_summarize_smoke.py` runs end-to-end against `127.0.0.1:18765`. Verified live with all three scenarios (see `verification.md`). |
| Anvil 側が利用すべき request fields / timing が docs に明記される | Done. `docs/anvil-integration.md` carries the field table and the turn-lifecycle diagram. |
| S2-03 型 regression を検出できる | Done. The runner emits `assertion=regression-detected` when `avoid` keywords drop from `context_pack.items[].text`. Pinned by `test_smoke_runner_detects_s2_03_regression`. |
| S3-01/S5-01 型の効果を再評価できる | Done. The runner emits `assertion=effect-present` / `effect-missing` for each scenario's `next_hints` keywords. Live smoke produced `effect-present` for both. |
| port は `127.0.0.1:18765` を使い、port 3000 は使わない | Done. The runner refuses any URL containing `3000` (`test_smoke_runner_rejects_port_3000`). |

## Branch / fixture coordination

The S-scenario summary fixtures (`tests/fixtures/shared/anvil_eval_s*_action_summary.json`)
already live on `develop` via commits `fc80f54` and `d280e35`. This branch
intentionally does **not** re-add them; the runner reads them from
`tests/fixtures/shared/` by stable filename and reports
`fixture missing` if the branch hasn't been rebased onto develop. The
unit tests stage in-memory copies of the same shape so they pass
independently of branch state.
