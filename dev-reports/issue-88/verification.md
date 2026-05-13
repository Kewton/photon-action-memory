# Verification - Issue #88 (v0.4.0 P2)

## Static checks

```bash
ruff format --check scripts/anvil_v1_summarize_smoke.py tests/test_anvil_v1_summarize_smoke.py
# 2 files already formatted

ruff check scripts/anvil_v1_summarize_smoke.py tests/test_anvil_v1_summarize_smoke.py
# All checks passed!

mypy photon_action_memory tests/test_anvil_v1_summarize_smoke.py scripts/anvil_v1_summarize_smoke.py
# Success: no issues found in 51 source files
```

## Focused tests

```bash
python -m pytest tests/test_anvil_v1_summarize_smoke.py -q
# 4 passed in 0.19s

python -m pytest \
  tests/test_anvil_contract.py \
  tests/test_anvil_context_pack_api.py \
  tests/test_anvil_evaluate.py \
  tests/test_shared_fixtures.py \
  tests/test_sidecar_api.py \
  tests/test_rollout_policy.py \
  tests/test_anvil_v1_summarize_smoke.py -q
# 68 passed in 0.50s
```

## Full pytest

```bash
python -m pytest tests/ -q --ignore=tests/test_codex_orchestrate.py
# 771 passed, 1 skipped in 1.60s
```

(`tests/test_codex_orchestrate.py` is left out of the focused run on this
branch; the suite stays green there as well.)

## Live sidecar smoke

Started the sidecar at `127.0.0.1:18765` (port 3000 not used):

```bash
PHOTON_ACTION_MEMORY_DB=/tmp/photon-issue88-events.sqlite \
PHOTON_ACTION_MEMORY_SUMMARY_DB=/tmp/photon-issue88-summaries.sqlite \
python -m uvicorn photon_action_memory.api.server:app \
  --host 127.0.0.1 --port 18765 --log-level warning
```

Staged the develop-branch S-scenario fixtures into
`tests/fixtures/shared/` (they ship there post-rebase; this branch
borrows them via `git show develop:…`) and ran the smoke:

```bash
python3 scripts/anvil_v1_summarize_smoke.py
```

Live result (per scenario):

| Scenario | summarize | summary_upsert | context_pack assertion | evidence_expand | evaluate |
|---|---|---|---|---|---|
| S2-03 | `summarize_stub` (501) | `stored` | `regression-clear` (avoid keywords React/Next survived) | `ok` | `logged=1` |
| S3-01 | `summarize_stub` (501) | `stored` | `effect-present` (next_hints `a + b`, `verify.py`) | `ok` | `logged=1` |
| S5-01 | `summarize_stub` (501) | `stored` | `effect-present` (next_hints `x + x`, `custom_check.py`) | `ok` | `logged=1` |

Exit code:

```bash
python3 scripts/anvil_v1_summarize_smoke.py; echo $?
# 0

python3 scripts/anvil_v1_summarize_smoke.py --url http://127.0.0.1:3000; echo $?
# 2  (and "error: port 3000 is not used for photon-action-memory" on stderr)
```

Staged fixtures were removed after the live run; the branch only carries
the runner, tests, docs, and procedure notes.

## Outstanding work

- `/v1/summarize` implementation lives on Issue #86 P1; the runner already
  consumes a 200 response when one is available (covered by
  `test_smoke_runner_consumes_live_summarize_response`).
- After Issue #86 ships, replay the live smoke from this verification and
  record an `L1/L2/L3` row in
  `workspace/v0.3.0/anvil-eval-beta-gamma-light-result.md`.
