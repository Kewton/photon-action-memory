# Design Note - Issue #88 (v0.4.0 P2)

## Objective

Prepare the integration smoke and evaluation procedure for `/v1/summarize`
so that, once the endpoint is implemented in P1 (Issue #86), Anvil can be
operated against the local sidecar with a reproducible turn lifecycle:

```
/v1/summarize → /v1/summary/upsert → /v1/context/pack
              → optional /v1/evidence/expand → /v1/evaluate
```

## Scope

This issue is procedure-only. Endpoint behavior changes belong to P0/P1
(Issues #82, #83, #84, #86). On this branch, `/v1/summarize` is still the
M2 501 stub, so the smoke must:

- Be **shaped for the post-implementation contract**, while
- Remaining runnable today: the procedure document explicitly notes which
  step depends on the P1 implementation, and the smoke script handles the
  501 path with a graceful skip + clear message.

## Deliverables

| Path | Purpose |
|---|---|
| `docs/photon-action-memory.md` | Add `/v1/summarize` smoke command and forward-looking 200 / current 501 expectations. |
| `docs/anvil-integration.md` | Add Anvil-side `/v1/summarize` request fields and turn-lifecycle timing. |
| `workspace/v0.3.0/anvil-eval-beta-gamma-light-result.md` | Lightweight eval result template covering the S2-03 / S3-01 / S5-01 scenarios used to detect regressions and re-evaluate effects. |
| `scripts/anvil_v1_summarize_smoke.py` | Runnable end-to-end smoke that drives the full turn lifecycle against `127.0.0.1:18765`. |
| `tests/test_anvil_v1_summarize_smoke.py` | Focused test that pins the smoke runner against the FastAPI `TestClient` and covers both the 200 (post-P1) and 501 (current stub) paths. |

## Anvil-side request fields and timing

```text
turn boundary
  ├─ build chunks from this turn's events
  ├─ POST /v1/summarize { chunk_ids, summary_level, policy }      ← new in v0.4.0
  │   └─ returns { summary, validation }
  ├─ POST /v1/summary/upsert { summary }                          ← store the summary
  ├─ POST /v1/context/pack { candidate_summary_ids?, repo, task } ← next-turn prep
  ├─ (optional) POST /v1/evidence/expand { evidence_ids, policy } ← evidence-on-demand
  └─ POST /v1/evaluate { context_pack_event }                     ← always called
```

The Anvil-side fields and ordering are codified in
`docs/anvil-integration.md` so Anvil engineers can implement the new
`/v1/summarize` call without re-reading photon-side code.

## Scenarios

Three scenarios from the existing Anvil eval matrix anchor this smoke:

| Scenario | What it proves | Regression / Effect |
|---|---|---|
| S2-03 | SvelteKit page edit; `avoid: React / Next` must survive context-pack admission. | **Regression**: any change that drops `avoid` guidance from context pack items would re-allow the misleading hint. |
| S3-01 | `calculator.py add()` bug fix; `next_hints` reach the prompt-visible items. | **Effect**: confirms that grounded `next_hints` shorten time-to-fix vs photon-off baseline. |
| S5-01 | `tool.py double()` bug fix + ANVIL.md preferred-verifier hint. | **Effect**: confirms that `avoid: pytest` + `next_hints` correctly steers the agent away from the wrong verifier. |

These three are tagged "beta-gamma-light" because they form a quick
sweep across two regression families (avoid-survival, hint-survival)
with one duplicate (S5-01) used to confirm stability under repeated runs.

## Out of scope

- Implementing `/v1/summarize`. Owned by Issue #86 P1.
- Adding the S-scenario fixture files. They already exist on `develop`
  via commits `fc80f54` and `d280e35`; the integration smoke references
  them by stable filename without recreating them on this branch.
- Adding/changing rollout gates. Owned by `workspace/anvil/rollout_policy.md`.

## Safety Notes

- All examples use `127.0.0.1:18765`. Port `3000` is never used.
- The smoke script never sends raw stdout/stderr; raw evidence stays on
  the sidecar admission deny list.
- The 501 fallback path is explicit: the smoke prints `summarize_stub`
  and continues with `/v1/summary/upsert` so the rest of the turn
  lifecycle is still exercised end-to-end.
