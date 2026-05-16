# Issue #119 Design — Answer-leak detection at seed upsert

## Goal

Reject (or warn on) `ActionSummary` seeds whose prompt-visible text
*pre-spoils the answer* of the task the seed will later be retrieved
for. A typical example is an Anvil S1-02 seed that says
"`summarize.py` prints a JSON object with keys `alpha`, `beta`,
`total`" — the task is to run the script and report stdout, but the
seed already enumerates the answer keys, so the agent can shortcut
without actually running anything.

This is the next layer of the Action Context Firewall after the
contradiction detector (#110): both are pure, syntax-based gates that
must run on every `/v1/summary/upsert` without LLM latency.

## Scope

In:

- New pure-function module `photon_action_memory/governance/answer_leak.py`
  with `ANSWER_LEAK_PATTERNS` (regex SSOT), `detect_answer_leak`,
  `evaluate_summary_quality`, `LeakMatch`, and `QualityReport`.
- `PHOTON_QUALITY_GATE_MODE` env var (`strict`/`warn`/`observe`,
  default `warn`).
- `ActionSummary.quality_warnings` and `ActionSummary.quality_check_status`
  fields (backwards-compatible defaults).
- Wire the gate into `server.py::upsert_summary`.
- Persist `quality_check_status` as a dedicated SQLite column with a
  one-shot migration (`ALTER TABLE ... ADD COLUMN`).
- Confidence attenuation in `FeedbackAdjustedContextScorer` when a
  retrieved seed carries `quality_check_status == "warned"`.
- Regression tests AL-01 (S1-02 positive), AL-02 (false-positive
  prevention), AL-03 (strict/warn/observe behaviour), AL-04 (semantic
  similarity case — placeholder skipped until layer B lands).

Out:

- Layer-B embedding/semantic similarity check (signature reserved but
  not implemented — tracked as a follow-up).
- Auto-rewrite of leaky seed text.
- Retroactive recheck of already-stored seeds (the migration sets the
  column default to `"unchecked"`; a backfill job is a follow-up).

## Detection patterns

`ANSWER_LEAK_PATTERNS` is a list of `(name, pattern)` tuples compiled
once at module import. The set is intentionally conservative — every
pattern must fire on a real "answer leak" pattern observed in Anvil
evaluation seeds (S1-02 family) without firing on legitimate context
text like `summarize.py reads JSON files`.

| name | matches | example |
|------|---------|---------|
| `output_literal_json` | inline JSON object literal containing one or more `"key": value` pairs in prompt-visible text | `the script outputs {"alpha": 10, "beta": 20}` |
| `output_key_enumeration` | "with keys / fields / columns ... X, Y, Z" or "keys are X, Y, Z" — three+ identifiers enumerated as answer schema | `prints a JSON object with keys alpha, beta, and total` |
| `direct_print_answer` | "prints / outputs / returns / shows a JSON object" — describes the answer shape in declarative voice | `summarize.py prints a JSON object` |
| `stdout_forecast` | "stdout (will / contains / shows / is) ..." — forecasts the stdout content | `stdout will be {"x": 1}` |
| `answer_assertion` | "the (answer / result / output / response) is ..." | `the answer is 30` |
| `numeric_answer_equality` | a standalone `= N` or `equals N` assertion outside code context | `total equals 30` |

All patterns are case-insensitive (`re.IGNORECASE`) and anchored at
word boundaries where possible. Pattern compilation lives in the
module so callers receive `LeakMatch(pattern_name, span, snippet)`
records without re-compiling.

## Public API

```python
from photon_action_memory.governance.answer_leak import (
    ANSWER_LEAK_PATTERNS,
    LeakMatch,
    QualityReport,
    detect_answer_leak,
    evaluate_summary_quality,
)

matches: list[LeakMatch] = detect_answer_leak(text)
report: QualityReport = evaluate_summary_quality(summary)
```

`QualityReport` carries:

- `status`: `"clean"` | `"warned"` | `"rejected"`
  (`"rejected"` is only produced when the caller asks for strict mode
  via the server wrapper; the pure function returns `"clean"` or
  `"warned"` only.)
- `warnings`: tuple of human-readable strings naming the field path
  and the pattern (e.g.
  `facts[0].text: output_key_enumeration: 'with keys alpha, beta, and total'`).
- `matches`: tuple of `LeakMatch` for caller introspection.

The function walks `summary.facts[*].text`, `summary.next_hints[*].reason`,
`summary.next_hints[*].target`, and `summary.avoid[*].reason` (the
prompt-visible text fields). `actions_done` and `failed_attempts` are
not scanned — they describe past actions, not the answer.

## Server wiring

`server.py::upsert_summary` resolves the mode from
`PHOTON_QUALITY_GATE_MODE` (case-insensitive, unknown values fall
back to `warn`):

- `strict`: any leak match → `HTTP 422` with
  `{"detail": "...", "quality_warnings": [...]}` and the seed is
  **not** persisted.
- `warn` (default): seed is persisted with
  `quality_check_status = "warned"` and `quality_warnings` populated;
  response status is `stored_with_warnings`.
- `observe`: seed is persisted unchanged; the report is logged at
  WARNING level so operators can size impact before flipping to
  `warn` or `strict`.

Clean summaries get `quality_check_status = "clean"` and an empty
`quality_warnings` regardless of mode.

## Schema additions

`ActionSummary` (in `api/schema_v2.py`):

- `quality_warnings: list[str] = Field(default_factory=list)`
- `quality_check_status: QualityCheckStatus | str = "unchecked"`

`QualityCheckStatus = Literal["unchecked", "clean", "warned", "rejected"]`.

Defaulting to `"unchecked"` (not `"clean"`) is deliberate: existing
persisted summaries that never went through the gate must not be
silently labelled "clean", but they also must not be treated as
"warned" by the downstream scorer. `unchecked` means "no signal" and
attenuation does not trigger.

## DB schema migration

`summary_store._initialize_schema` gains an idempotent migration:

```python
columns = {row["name"] for row in self._connection.execute(
    "PRAGMA table_info(action_summaries)"
).fetchall()}
if "quality_check_status" not in columns:
    self._connection.execute(
        "ALTER TABLE action_summaries ADD COLUMN "
        "quality_check_status TEXT NOT NULL DEFAULT 'unchecked'"
    )
```

`upsert` reads `summary.quality_check_status` and writes it into the
new column, and `search`/`get`/`resolve` continue to round-trip
through `payload_json` (the column is duplicate for query/index
purposes, the JSON is the source of truth).

The column is indexed (`idx_summaries_quality`) so future audits like
"list all warned seeds" stay cheap.

## Feedback attenuation

`FeedbackAdjustedContextScorer.score_admission` and
`score_summary_usefulness` apply a multiplicative attenuation when
`summary.quality_check_status == "warned"`:

```python
QUALITY_WARNED_FACTOR = 0.5
if summary.quality_check_status == "warned":
    new_score = min(new_score, base.score * QUALITY_WARNED_FACTOR)
```

The factor 0.5 is conservative — it halves the admission score
without zeroing it, so the seed can still surface when nothing else
matches. `quality_check_status == "rejected"` should never appear in
storage (strict mode refuses to persist), but if it did we'd treat
it like `unsafe`: hard-capped at `CONTRADICTED_MAX_SCORE`.

## Test plan

- `tests/test_answer_leak.py::test_al01_positive_s1_02` — feed the
  existing `anvil_eval_s1_02_action_summary.json` (which contains the
  "prints a JSON object with keys alpha, beta, and total" line) to
  `evaluate_summary_quality` and assert status is `"warned"` with at
  least one `output_key_enumeration` or `direct_print_answer` match.
- `tests/test_answer_leak.py::test_al02_false_positive_prevention` —
  a `Fact(text="summarize.py reads JSON files and validates them")`
  must yield status `"clean"`.
- `tests/test_answer_leak.py::test_al03_strict_mode_rejects`,
  `test_al03_warn_mode_annotates`,
  `test_al03_observe_mode_passes_through` — drive the
  `/v1/summary/upsert` endpoint via `TestClient` with each
  `PHOTON_QUALITY_GATE_MODE` and assert the documented outcomes.
- `tests/test_answer_leak.py::test_al04_semantic_similarity_layer_b` —
  marked `pytest.skip("layer B not implemented in Issue #119")`; the
  test name reserves the slot for the follow-up.

## Open questions

- Should we attenuate inside `_summary_prompt_text`-driven gates as
  well (e.g. task-aware quality gate) when the seed is warned?
  Currently no — those gates already have their own logic and
  stacking the attenuation risks double-counting.
- Backfill of `quality_check_status` on already-stored seeds is left
  as a follow-up; the column defaults to `"unchecked"` so they retain
  their current behaviour.
