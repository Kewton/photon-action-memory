# Anvil ↔ photon-action-memory: Rollout Policy

This document defines the promotion criteria for the Anvil photon-action-memory
integration, moving from **shadow mode** (observe only) to **canary mode**
(live injection for a fraction of Anvil sessions).

---

## Phase overview

| Phase | Injection | Metrics collection | Promotion gate |
|---|---|---|---|
| Shadow | None — context pack is built but never sent to the prompt | All rollout metrics recorded as `shadow_not_injected` | Satisfy all canary gates below |
| Canary | Live injection for a configurable percentage of sessions | Full adoption + pollution metrics | Satisfy rollback safety thresholds |
| Full rollout | Live injection for all eligible sessions | Ongoing monitoring | N/A |

---

## Shadow → Canary checklist

Before promoting to canary, **all** of the following must be green.

### Gate 1 — Minimum turn count

- **Condition**: `total_turns >= 10` (configurable via `CanaryRolloutPolicy.min_turns_for_canary`)
- **Why**: A shadow run with fewer than 10 turns does not provide sufficient
  statistical signal that the context pack behaves safely.
- **Check**: `build_rollout_metrics(eval_records).canary_eligible`

### Gate 2 — Zero raw tool tokens in prompt

- **Condition**: `total_raw_tool_tokens_in_prompt == 0`
- **Why**: Any non-zero value means raw stdout/stderr or raw tool output leaked
  into the injected context, which violates the Anvil safety contract. This is a
  hard gate; there is no threshold.
- **Check**: `PollutionReport.total_raw_tool_tokens_in_prompt` from
  `build_pollution_report(pollution_records)`

### Gate 3 — Low fail-open incident rate

- **Condition**: `(error_count + not_available_count) / total_turns <= 0.05`
  (configurable via `CanaryRolloutPolicy.max_fail_open_rate`)
- **Why**: A high rate of sidecar errors or timeouts indicates instability that
  should be resolved before live injection.
- **Check**: `build_rollout_metrics(eval_records).fail_open_incident_rate`

---

## Rollback conditions

If **any** of the following is observed in canary or shadow mode, the integration
must be rolled back immediately (revert to shadow or disable):

| Condition | Signal | Action |
|---|---|---|
| `total_raw_tool_tokens_in_prompt > 0` | Raw tool output in prompt | Immediate rollback — disable injection |
| `fail_open_incident_rate > max_fail_open_rate` | Sidecar errors / timeouts too frequent | Rollback — investigate sidecar stability |
| Adoption rate collapses to 0 for multiple consecutive turns | Context pack systematically ignored | Investigate context pack quality |
| Stale summary incidents spike | Summaries invalidated too frequently | Rollback + review summary store staleness policy |

---

## API helpers

### `is_canary_eligible(turn_count, raw_tool_tokens_in_prompt, *, fail_open_incident_rate, policy)`

Located in `photon_action_memory/context/canary.py`.

Returns `(eligible: bool, reason: str)`. Checks all three gates in order:
turn count → raw tool tokens → fail-open rate.

```python
from photon_action_memory.context.canary import CanaryRolloutPolicy, is_canary_eligible

policy = CanaryRolloutPolicy(min_turns_for_canary=10, max_fail_open_rate=0.05)
eligible, reason = is_canary_eligible(
    turn_count=42,
    raw_tool_tokens_in_prompt=0,
    fail_open_incident_rate=0.02,
    policy=policy,
)
# → (True, "eligible for canary")
```

### `build_rollout_metrics(eval_records, *, raw_tool_tokens_in_prompt, min_turns_for_canary, max_fail_open_rate)`

Located in `photon_action_memory/eval/metrics.py`.

Accepts a sequence of Anvil evaluate records (same shape as stored by
`/v1/evaluate`) and the aggregate raw-tool-token count from the pollution report.
Returns a `RolloutMetrics` instance with `canary_eligible`, `rollback_triggered`,
and human-readable reasons.

```python
from photon_action_memory.eval.metrics import build_rollout_metrics
from photon_action_memory.eval.pollution import build_pollution_report

pollution = build_pollution_report(pollution_records)
metrics = build_rollout_metrics(
    eval_records,
    raw_tool_tokens_in_prompt=pollution.total_raw_tool_tokens_in_prompt,
    min_turns_for_canary=10,
    max_fail_open_rate=0.05,
)
if metrics.rollback_triggered:
    raise RuntimeError(f"rollback: {metrics.rollback_reason}")
if not metrics.canary_eligible:
    print(f"not yet eligible: {metrics.ineligible_reason}")
```

---

## Fixture tests

The fixture at `tests/fixtures/v0.2/rollout_metrics_fixture.json` contains four
named scenarios:

| Scenario | `total_turns` | `raw_tool_tokens_in_prompt` | Expected outcome |
|---|---|---|---|
| `canary_ready` | 10 | 0 | `canary_eligible=True`, `rollback_triggered=False` |
| `too_few_turns` | 5 | 0 | `canary_eligible=False` (turn count gate) |
| `raw_tool_leak` | 10 | 124 | `rollback_triggered=True`, `canary_eligible=False` |
| `high_fail_open` | 10 | 0 | `rollback_triggered=True`, `fail_open_incident_rate=0.30` |

Run with: `python -m pytest tests/test_rollout_policy.py -v`
