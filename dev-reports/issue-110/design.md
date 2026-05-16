# Issue #110 Design — Contradiction detection across seeds

## Goal

Flag conflicting `ActionSummary` seeds inside the same
`repo_id + task_signature` scope, surface the conflict in audit reports,
and emit a `ContextPack` warning when retrieved seeds disagree. Detection
must be syntax-based (no LLM call) so it can run on every seed insertion
and on every `/v1/context/pack` request without latency cost.

## Scope

In:

- A pure-function module `photon_action_memory/governance/contradiction.py`.
- New `needs_review` value for `ValidityStatusKind`.
- A new `POST /v1/seeds/audit/contradictions` endpoint.
- A `photon-audit` CLI script for ad-hoc audits.
- `_resolve_context_summaries` emits a `contradiction_detected` warning
  when admitted seeds conflict.
- Quality gate path can mark a freshly upserted seed `needs_review` when
  it conflicts with an existing seed in the same scope.

Out (not required by Issue #110):

- LLM-based semantic conflict detection.
- Auto-resolution / merge of conflicting seeds.
- UI surfaces beyond CLI / API JSON.

## Detection rules

`detect_contradictions(summaries)` returns a list of
`ContradictionPair(summary_a_id, summary_b_id, kind, evidence)` records.

For each ordered pair `(a, b)` of summaries in the same `repo_id +
task_signature` scope (universal seeds compared against any other seed
sharing detected metadata are out of scope; we restrict by repo+task to
keep the pair count bounded), the following syntax checks fire:

1. `avoid_vs_action` — token overlap between `a.avoid[*].action` and
   `b.actions_done[*].command` / `b.actions_done[*].target` /
   `b.next_hints[*].target` ≥ 0.5 Jaccard.
2. `avoid_vs_avoid_negation` — `a.avoid[*].action` and
   `b.avoid[*].action` overlap by ≥ 0.5 Jaccard but their `reason` text
   contains opposite polarity markers (e.g. `do not use X` vs `use X
   instead`).
3. `fact_negation` — two facts with ≥ 0.5 token Jaccard but opposite
   polarity, where polarity is detected by leading negation tokens
   (`not`, `no`, `never`, `cannot`, `must not`, `do not`, `しない`,
   `ない`) on otherwise-overlapping content.
4. `next_hint_conflict` — overlapping `next_hints[*].target` on opposite
   verbs (`add` vs `remove`, `enable` vs `disable`, `use` vs `do not
   use`, `keep` vs `delete`).
5. `failed_attempt_vs_next_hint` — `a.failed_attempts[*].action`
   overlaps `b.next_hints[*].target` (suggesting an action already known
   to fail). Token overlap ≥ 0.6 Jaccard.

Each rule is implemented as a small pure function over `ActionSummary`
sub-models. Token comparison reuses
`photon_action_memory.context.overlap_detector.tokenize` (default
`ascii` mode) so the behaviour matches the existing quality gate.

## Schema additions

- `ValidityStatusKind` gains `"needs_review"` so a seed that is found
  to contradict another can be marked without being treated as
  immediately stale or contradicted (which would suppress retrieval).
- `_STALENESS_RISK` and `_VALIDITY_ADMISSION_FACTOR` (in
  `models/context_scorer.py`) get a `needs_review` entry between
  `partial` and `stale` so existing scoring code stays consistent.
- `SummaryRetriever._STALE_STATUSES` is unchanged — `needs_review`
  seeds remain retrievable but the contradiction warning fires.

## API surface

`POST /v1/seeds/audit/contradictions`

Request body:

```jsonc
{
  "schema_version": "action-memory.v0.2",
  "request_id": "<uuid>",
  "repo_id": "optional",
  "task_signature": "optional",
  "limit": 200
}
```

Response body:

```jsonc
{
  "schema_version": "action-memory.v0.2",
  "request_id": "<uuid>",
  "pairs": [
    {
      "summary_a_id": "...",
      "summary_b_id": "...",
      "kind": "avoid_vs_action",
      "evidence": "do not use foo  vs  command 'use foo'"
    }
  ],
  "scanned": 42
}
```

The endpoint loads summaries from `SummaryStore`, scopes by
`repo_id+task_signature` (or all summaries when both are `None`), groups
by scope, then runs `detect_contradictions` per scope.

## Context pack warning

Inside `_resolve_context_summaries`, after the four-stage retrieval
returns the final `results` list, the resolver runs
`detect_contradictions(results)` and forwards each detected pair as a
`ContextPackWarning(kind="contradiction_detected", message=…)`. The
warning is appended through a new `extra_warnings` parameter on
`build_context_pack` (or by mutating `route_warnings` before pack
construction — the simpler option).

## CLI

`photon_action_memory/cli/audit.py` exposes a `photon-audit` script
with subcommands:

```
photon-audit detect-contradictions [--url URL] [--repo-id R] [--task-signature T]
```

Implemented in the existing CLI style (`urllib.request`, no extra
deps). `pyproject.toml` adds the `photon-audit` console script entry
pointing at `photon_action_memory.cli.audit:main`.

## Tests

Unit (`tests/test_contradiction_detection.py`, ≥ 12 cases):

1. Empty input returns `[]`.
2. Single summary returns `[]`.
3. `avoid` vs `actions_done` clear conflict.
4. `avoid` vs `actions_done` token-disjoint → no conflict.
5. `avoid` vs `avoid` polarity opposite.
6. `avoid` vs `avoid` same polarity → no conflict.
7. Fact negation (English `not`).
8. Fact negation (Japanese `しない`).
9. Fact overlap with no negation → no conflict.
10. `next_hint` opposite verbs (`enable` vs `disable`).
11. `next_hint` synonymous verbs → no conflict.
12. `failed_attempt` vs `next_hint` overlap.
13. Different `repo_id` → not paired (scope filter).
14. Different `task_signature` → not paired.

Integration (`tests/test_contradiction_detection_api.py`):

- `POST /v1/seeds/audit/contradictions` returns expected pairs after
  upserting two conflicting seeds.
- `POST /v1/context/pack` emits a `contradiction_detected` warning when
  both seeds match the request.
- Resolution flow: marking the older seed as `validity.status =
  "needs_review"` keeps it retrievable but the warning still fires;
  marking it `contradicted` makes it disappear from the pack.

## File map

- `photon_action_memory/governance/__init__.py` (new package)
- `photon_action_memory/governance/contradiction.py` (new)
- `photon_action_memory/api/schema_v2.py` (extend
  `ValidityStatusKind`, add audit request/response models)
- `photon_action_memory/api/server.py` (new endpoint, warning emission)
- `photon_action_memory/cli/audit.py` (new)
- `pyproject.toml` (`photon-audit` script)
- `photon_action_memory/models/context_scorer.py` (scoring constants)
- `tests/test_contradiction_detection.py` (new)
- `tests/test_contradiction_detection_api.py` (new)
