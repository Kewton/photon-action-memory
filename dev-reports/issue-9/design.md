# Issue #9 Design Note

## Scope

Implement the minimum offline / shadow-mode evaluation surface needed for M6:

- compute aggregate metrics from a fixed, normalized fixture;
- run evaluation without emitting raw per-turn logs;
- optionally write only a commit-friendly aggregate JSON summary;
- keep the test fixture lightweight enough for normal CI.

## Approach

`photon_action_memory.eval.metrics` will own the report data model and metric
calculation. The input is a list of normalized shadow records rather than raw
agent logs. Each record includes suggested actions, evidence ids, the actual next
action, outcome, latency, and sidecar status. The generated report contains only
counts, rates, and latency percentiles.

`photon_action_memory.eval.runner` will validate fixture records, call the
metrics module, and optionally write deterministic JSON. It will not return or
write individual records, summaries, prompts, tool output, or other raw log
fields. The runner's public contract is an aggregate `MetricsReport`.

Focused pytest coverage will use an in-memory fixed fixture and a temporary
output path to verify metric values and confirm the serialized output contains
only aggregate summary keys.
