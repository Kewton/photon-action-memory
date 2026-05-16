# Issue #121 Design — LLM draft summary + PHOTON/MLX scorer (v0.4.0)

## Goal

Open two opt-in seams in Action Memory while keeping the default path
deterministic and fail-open:

1. A `SummaryGeneratorProtocol` so the rule-based
   `ActionSummaryBuilder` can be swapped for an LLM-backed
   `LLMDraftSummaryGenerator` (Qwen/MLX) when explicitly enabled.
2. An `ActionMemoryPhotonScorer` boundary that ranks
   summary / evidence / next_hint / failed_attempt candidates via the
   PHOTON checkpoint when available, and falls back to a deterministic
   scorer when MLX or the checkpoint is missing.

Every new code path is opt-in via env. `default == rule_based`,
`default scorer == deterministic`. CI must never download a model.

## Scope

In:

- `photon_action_memory/memory/summary_generator.py` — protocol +
  rule-based wrapper (existing `ActionSummaryBuilder` behaviour) +
  `make_summary_generator()` factory + closed-enum
  `SummaryGeneratorReport`.
- `photon_action_memory/memory/llm_draft_summary.py` — lazy
  `LLMDraftSummaryGenerator`, `SummaryDraftEventFrame` allowlist DTO,
  `LLMDraftConfig`, prompt builder, JSON parser, fallback enum.
- `photon_action_memory/models/photon_scorer.py` —
  `ActionMemoryPhotonScorer` protocol + DTOs (`SummaryCandidate`,
  `EvidenceCandidate`, `NextHintCandidate`, `FailedAttemptCandidate`,
  `ActionMemoryScoreResult`) + `DeterministicActionMemoryScorer`
  fallback + `PhotonMLXActionMemoryScorer` thin wrapper +
  `make_action_memory_scorer()` factory.
- Schema extension: `SummaryGeneratorReport` reused on
  `SummarizeResponse` via two new optional fields (`generator_used`,
  `generator_fallback_reason`). Defaults preserve existing payloads.
- `/v1/summarize` integration: route stored-event and inline-chunk
  paths through the configured generator; emit telemetry; keep
  `status` semantics from spec (`ok`, `degraded`,
  `fallback_rule_based`, `rejected`, `aborted`).
- `/v1/summary/upsert` status semantics: existing `stored`,
  `stored_with_warnings`; add `rejected` for the strict-mode 422
  pathway as a documented enum (current implementation already raises
  422 — we just normalize the enum and document it).
- Focused tests in
  `tests/test_summary_generator.py`,
  `tests/test_llm_draft_summary.py`,
  `tests/test_action_memory_scorer.py`,
  `tests/test_summarize_endpoint.py` (new cases only).

Out:

- Default-on LLM summary.
- Bypassing schema validation, fidelity, or answer-leak gates for
  LLM output.
- PHOTON generation (LLM output uses only the lazy Qwen path; PHOTON
  is purely a scorer).
- CI/import-time model download. The lazy import must raise on
  missing packages, never network-fetch.
- Anvil/UAT report generation (separate Issue).

## Phase 1 — SummaryGeneratorProtocol

`photon_action_memory/memory/summary_generator.py`:

```python
class SummaryGeneratorReport(Protocol-friendly dataclass):
    generator_used: Literal["rule_based", "llm"]
    fallback_reason: SummaryGeneratorFallbackReason | None
    notes: tuple[str, ...] = ()

SummaryGeneratorFallbackReason = Literal[
    "mlx_unavailable",
    "model_unavailable",
    "generation_exception",
    "empty_output",
    "invalid_json",
    "schema_validation_failed",
    "quality_gate_rejected",
    "fidelity_invalid",
    "disabled",
]

class SummaryGeneratorProtocol(Protocol):
    def build(
        self,
        chunk: ActionChunk,
        *,
        summary_id: str | None = None,
        evidence_records: Sequence[Mapping[str, Any]] | None = None,
    ) -> tuple[ActionSummary, SummaryGeneratorReport]: ...
```

`RuleBasedSummaryGenerator` wraps the existing
`ActionSummaryBuilder().build(...)` and always returns
`SummaryGeneratorReport(generator_used="rule_based", fallback_reason=None)`.
`evidence_records` is accepted for protocol parity but unused.

The factory `make_summary_generator(env=os.environ)` reads
`PHOTON_SUMMARY_GENERATOR` (case-insensitive). Unknown values fall
back to `"rule_based"` so a misconfigured deployment never silently
flips on LLM mode. When `llm` is requested it tries to construct
`LLMDraftSummaryGenerator`; if construction itself raises a known
unavailability error the factory still returns a wrapper that always
delegates to rule-based and surfaces the fallback reason on each
call (so callers see `generator_used="rule_based"`,
`fallback_reason="model_unavailable"` etc.).

## Phase 2 — LLM draft generator

`photon_action_memory/memory/llm_draft_summary.py`:

- `LLMDraftConfig`: dataclass holding `model`, `temperature`,
  `max_tokens`, `seed`, `fallback_policy`. Loaded from env in factory.
- `SummaryDraftEventFrame`: allowlist DTO. Fields are
  `chunk_id`, `kind`, `outcome`, `evidence_ids: tuple[str, ...]`,
  `summary` (already-redacted chunk.summary), and an optional
  sanitized `event_excerpts: tuple[SummaryDraftEvent, ...]` built from
  the supplied `evidence_records`. Each excerpt is capped at
  `_EVIDENCE_EXCERPT_CHARS` (≤320), sanitized via
  `sanitize_text_with_report`, and skipped if `has_sensitive_content`
  still flags it. Raw stdout/stderr, full diff, full user prompt,
  stack traces, secrets, and home paths never reach the prompt.
- `LLMDraftSummaryGenerator.build(chunk, evidence_records=...)`:
  1. Build a `SummaryDraftEventFrame` (always allowlist; on failure →
     `generation_exception` fallback).
  2. Construct the user prompt from the frame; system prompt is a
     constant inside the module (no f-string of dynamic raw text).
  3. Invoke the lazy MLX adapter. Any `ModuleNotFoundError` or
     `MlxUnavailable` → `mlx_unavailable`. Missing model file →
     `model_unavailable`. Any other generation exception is caught;
     only `type(exc).__name__` is logged (never `exc.args`) →
     `generation_exception`.
  4. `_parse_json(output)`: empty → `empty_output`; not valid JSON →
     `invalid_json`. We deliberately do not log the offending output.
  5. `_validate_schema(parsed, chunk)`: rebuild as `ActionSummary`;
     enforce that every `fact.evidence_ids` entry is in
     `chunk.event_ids` (LLM cannot invent evidence). On failure →
     `schema_validation_failed`.
  6. `SummaryCanonicalizer().canonicalize` strips ungrounded facts.
  7. `evaluate_summary_quality`: if `warned` and policy is `strict`,
     fall back with `quality_gate_rejected`; otherwise propagate to
     report.
  8. Optional `SummaryFidelityChecker.check` when evidence_records
     given: if status is `invalid`, fall back with
     `fidelity_invalid`.
  9. On success → `(summary, report(generator_used="llm",
     fallback_reason=None))`.

  On any fallback step, the generator computes a deterministic
  rule-based summary by delegating to `RuleBasedSummaryGenerator` and
  returns it with `generator_used="rule_based"` and the closed-enum
  fallback reason set. `PHOTON_SUMMARY_LLM_FALLBACK_POLICY=abort`
  raises `SummaryGenerationAborted` instead (server then maps to
  `status="aborted"`).

`_load_mlx_generator(config)`: pure lazy import. Returns a callable
`(prompt) -> str`. On `ModuleNotFoundError("mlx*"|"mlx_lm*")` raises
`MlxUnavailable`. On missing model directory raises
`ModelUnavailable`. The MLX generation kwargs (no-think system tag,
deterministic seed) live here so the rest of the module is
test-friendly without MLX installed. Tests inject a fake generator
via a `generator_callable` constructor parameter.

## Phase 3 — Validation, telemetry, server wiring

- `ActionSummary` gains no new required fields. The telemetry is
  exposed on `SummarizeResponse` directly:

  ```python
  generator_used: Literal["rule_based", "llm"] = "rule_based"
  generator_fallback_reason: SummaryGeneratorFallbackReason | None = None
  ```

- `/v1/summarize` (stored-event path):
  - Look up `make_summary_generator(env=os.environ)` once per app
    (cached on `app.state`).
  - For each chunk: `summary, report = generator.build(chunk, evidence_records=records)`.
  - Apply canonicalizer + answer-leak gate as today (LLM output cannot
    bypass either; the generator already canonicalized but the
    server still runs the gate so behaviour matches rule-based path).
  - Aggregate report: any fallback in any chunk wins (the response
    reports the worst). All chunks `generator_used="llm"` →
    `generator_used="llm"`. Any non-`None` fallback_reason →
    response uses that reason (first wins; ties favour `disabled` <
    others).
  - `status`:
    - All `llm` no-fallback → `"ok"`.
    - Any `fallback_reason in {empty_output, invalid_json,
      schema_validation_failed, generation_exception,
      mlx_unavailable, model_unavailable}` → `"fallback_rule_based"`.
    - `quality_gate_rejected` strict + warn modes → `"degraded"`.
    - `SummaryGenerationAborted` → `"aborted"` with no
      `summaries_upserted`.

- `/v1/summarize` (inline-chunks path): same plumbing — generator is
  called per chunk during `_build_hierarchical_summary` (refactored
  to accept the generator).

- `/v1/summarize` (firewall draft path): unchanged for v0.4.0. The
  upload-a-draft path is for callers already producing LLM output
  outside the sidecar; our firewall and grounding checks still run.

- `/v1/summary/upsert`: keep current strict 422 behaviour; document
  `rejected` as the strict-mode status enum value in the design.
  No code change needed beyond schema docstring.

- Env (`make_summary_generator`):
  - `PHOTON_SUMMARY_GENERATOR` — `rule_based`(default) | `llm`.
  - `PHOTON_SUMMARY_LLM_MODEL` — model identifier passed to MLX
    loader. Default: `mlx-community/Qwen2.5-7B-Instruct-4bit`.
  - `PHOTON_SUMMARY_LLM_FALLBACK_POLICY` — `rule_based`(default) |
    `abort`.
  - `PHOTON_SUMMARY_LLM_TEMPERATURE` — float, default `0.1`.
  - `PHOTON_SUMMARY_LLM_MAX_TOKENS` — int, default `512`.
  - `PHOTON_SUMMARY_LLM_SEED` — int, default `1729`.

## Phase 4 — Action Memory PHOTON scorer

`photon_action_memory/models/photon_scorer.py`:

```python
@dataclass(frozen=True)
class SummaryCandidate:    summary_id, text, evidence_ids
@dataclass(frozen=True)
class EvidenceCandidate:   evidence_id, text
@dataclass(frozen=True)
class NextHintCandidate:   index, kind, reason, target | None
@dataclass(frozen=True)
class FailedAttemptCandidate: index, action, outcome

@dataclass(frozen=True)
class ActionMemoryScoreResult:
    summary_scores: tuple[ScoredSummary, ...]
    evidence_scores: tuple[ScoredEvidence, ...]
    next_hint_scores: tuple[ScoredNextHint, ...]
    failure_similarity: tuple[ScoredFailedAttempt, ...]
    drift_score: float | None
    model_version: str
    warnings: tuple[str, ...] = ()

class ActionMemoryPhotonScorer(Protocol):
    def score(
        self,
        *,
        request_id: str,
        repo_id: str | None,
        task_text: str,
        session_id: str | None,
        session_state_ref: None = None,
        candidate_summaries: Sequence[SummaryCandidate] = (),
        candidate_evidence: Sequence[EvidenceCandidate] = (),
        candidate_next_hints: Sequence[NextHintCandidate] = (),
        candidate_failed_attempts: Sequence[FailedAttemptCandidate] = (),
    ) -> ActionMemoryScoreResult: ...
```

`DeterministicActionMemoryScorer`:

- summary score = lexical overlap (token Jaccard) between
  `task_text` and `summary.text`, bounded [0, 1]; small boost for
  evidence presence (`+0.05` capped).
- evidence score = same overlap on evidence text.
- next_hint score = overlap on `reason || target`.
- failure similarity = overlap on `outcome || action`.
- `drift_score = None` (deterministic baseline cannot detect drift).
- `model_version = "deterministic-overlap-v1"`.
- `warnings = ("photon_unavailable",)` only when constructed via the
  factory after a PHOTON load failure; pure construction emits no
  warning.

`PhotonMLXActionMemoryScorer`: wraps `PhotonMLXAdapter`. Uses its
`_score` per candidate against a `PhotonScoringState` built from the
arguments. `model_version` comes from
`adapter.checkpoint.model_version` else `PHOTON_MODEL_VERSION`.
If construction or any candidate score raises
`PhotonAdapterError` / `CheckpointError`, the factory returns the
deterministic scorer with `("photon_unavailable",)` warning.

`make_action_memory_scorer(env=os.environ)`:

- If `configured_checkpoint_path(env)` is None →
  `DeterministicActionMemoryScorer()`.
- Otherwise try `PhotonMLXAdapter.from_checkpoint(path, strict=...)`;
  on failure → `DeterministicActionMemoryScorer(warning=...)`.

No /v1 endpoint wiring is added in this Issue (out of scope for the
plan’s Phase 4: the boundary is added so a follow-up can call it
from `/v1/context/pack` ranking). The unit tests assert that the
boundary works in both modes.

## Safety / no-leak invariants

- `SummaryDraftEventFrame` never carries raw command output, secrets,
  home paths, full diffs, or full user prompts. Every string is
  passed through `sanitize_text_with_report` and re-checked with
  `has_sensitive_content`; any excerpt that still trips the check is
  dropped from the frame.
- LLM output is fed through canonicalizer (drops ungrounded facts),
  fidelity checker, and answer-leak gate. None can be bypassed.
- `LLMDraftSummaryGenerator` rejects any `fact.evidence_ids` that
  references an event_id outside the source chunk — falls back with
  `schema_validation_failed`.
- Logging: only generator type, fallback reason enum, chunk_id; never
  raw prompt, raw model output, or exception args.
- The lazy import lives in `_load_mlx_generator` and is only called
  when `LLMDraftSummaryGenerator` is constructed via the factory in
  `llm` mode. Importing the module is free; running CI without
  `mlx_lm` installed must remain green.

## Test plan

`tests/test_summary_generator.py`:

- factory defaults to rule_based.
- `PHOTON_SUMMARY_GENERATOR=other` falls back to rule_based.
- rule_based generator output for a sample chunk is byte-equal to
  `ActionSummaryBuilder().build(...)` (regression on the default).

`tests/test_llm_draft_summary.py` (no MLX import required):

- happy path with an injected `generator_callable` returning a
  valid JSON ActionSummary → `generator_used="llm"`, no fallback.
- injected callable raises `MlxUnavailable` → fallback enum
  `mlx_unavailable`, summary equals rule-based output.
- injected callable returns `""` → `empty_output`.
- injected callable returns `"not json"` → `invalid_json`.
- callable returns JSON with `facts[0].evidence_ids=["evt_outside"]`
  → `schema_validation_failed`.
- callable returns JSON with answer-leak text in a fact →
  `quality_gate_rejected`.
- `PHOTON_SUMMARY_LLM_FALLBACK_POLICY=abort` raises
  `SummaryGenerationAborted` rather than falling back.
- `SummaryDraftEventFrame` strips secrets / home paths / raw
  command output before building the user prompt (assert against
  the prompt string).
- module import requires no `mlx` / `mlx_lm` install
  (smoke-tested by `tests/test_import.py` continuing to pass).

`tests/test_action_memory_scorer.py`:

- `DeterministicActionMemoryScorer.score(...)` returns scores in
  candidate order with `model_version="deterministic-overlap-v1"`.
- summary score on task overlap is higher than on no overlap.
- `make_action_memory_scorer()` returns deterministic when no
  checkpoint env is set.
- with a fake checkpoint env pointing at an invalid path, factory
  falls back to deterministic with `("photon_unavailable",)`
  warning.

`tests/test_summarize_endpoint.py` (additions, no new module):

- stored-events path with default env reports
  `generator_used="rule_based"`, `generator_fallback_reason=None`.
- stored-events path with `PHOTON_SUMMARY_GENERATOR=llm` and no MLX
  reports `generator_used="rule_based"`,
  `generator_fallback_reason="mlx_unavailable"`,
  `status="fallback_rule_based"`.

## Open questions / follow-ups

- Anvil/UAT comparison report is deferred to a v0.4.0 eval Issue.
- Wiring the new scorer into `/v1/context/pack` ranking is a
  follow-up; the boundary is added so it can plug in without churn.
- Backfill of stored summaries with `generator_used` metadata is not
  attempted; the field is response-only telemetry.
