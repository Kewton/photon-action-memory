# PHOTON Action Memory

Action-oriented memory and context-firewall sidecar for coding agents.

PHOTON Action Memory is a local-first memory controller. It learns from tool
loops, repository exploration, test results, and previous agent sessions to
help a coding agent choose the next file, command, evidence, or action.

It is not a general document RAG system. The central question is:

> Given the current coding task, repository state, recent tool results, and
> past sessions, what should the agent do next?

## Current Status

The repository now contains a working FastAPI sidecar with SQLite-backed event
and summary storage.

Implemented sidecar capabilities:

- `GET /health`
- `POST /v1/events`
- `POST /v1/suggest`
- `POST /v1/summarize`
- `POST /v1/summary/upsert`
- `POST /v1/summary/validate`
- `POST /v1/context/pack`
- `POST /v1/evidence/expand`
- `POST /v1/evaluate`

The default runtime path is deterministic and fail-open. MLX, local LLMs, and
PHOTON checkpoints are optional; the package must import, test, and run the
default sidecar without them installed.

## Core Capabilities

- Convert coding-agent event logs into `ActionChunk` and `ActionSummary`
  records.
- Keep prompt-visible memory behind an Action Context Firewall.
- Deny raw stdout/stderr by default and expose only admitted summaries or
  selected evidence snippets.
- Store summaries locally in SQLite and retrieve them by repo/task scope.
- Validate summaries for evidence grounding, stale or contradicted state, and
  answer-leak risks.
- Build `ContextPack` responses that respect a memory token budget.
- Expand evidence on demand by `evidence_id`.
- Log shadow/canary adoption and outcome data through `/v1/evaluate`.
- Generate summaries with the default rule-based generator or an opt-in local
  LLM draft generator.
- Build and test optional PHOTON/MLX checkpoint scorers while preserving
  deterministic fallback when a checkpoint or MLX runtime is unavailable.

## Memory Hierarchy

PHOTON Action Memory sits between short-lived working memory and long-term
knowledge stores.

```text
LLM
  ↓
Prompt / Context Window          L1
  ↓
Agent Working Memory             L2
  ↓
PHOTON Action Memory             L3
  ↓
Episodic / User Memory           Main Memory
  ↓
Repo Index / Vector DB / Graph   Storage
```

In this model, PHOTON Action Memory acts like an L3 action cache and context
firewall for coding agents.

## Target Integration

The first target integration is Anvil, a local-first coding agent.

The deployment model is a fail-open local sidecar:

```text
Coding Agent
  ↓
PHOTON Action Memory Sidecar
  ↓
Local Event Store / Summary Store
  ↓
Deterministic scorer / optional PHOTON scorer boundary
```

The agent remains responsible for final decisions and tool execution. PHOTON
Action Memory provides compact memory signals, evidence references, admission
decisions, and evaluation data.

Primary operations docs:

- `docs/photon-action-memory.md`: sidecar startup, storage, API smoke checks,
  optional LLM summary generation, and checkpoint scorer notes.
- `docs/anvil-integration.md`: Anvil env/defaults, shadow/canary/rollback
  checklists, shared fixture updates, and troubleshooting ownership.
- `workspace/anvil/summary.md`: Anvil-facing fixture and integration notes.
- `workspace/v0.4.0/`: v0.4.0 LLM/PHOTON planning and checkpoint scorer
  evaluation notes.

## Summary Generation

`POST /v1/summarize` is implemented. It builds and persists `ActionSummary`
objects from buffered chunks, inline chunks, or firewall-checked draft
summaries.

Default behavior:

```text
event log -> ActionChunk -> rule-based ActionSummary
```

The optional LLM draft path is enabled only by configuration:

```bash
PHOTON_SUMMARY_GENERATOR=llm \
python -m uvicorn photon_action_memory.api.server:app \
  --host 127.0.0.1 \
  --port 18765
```

The LLM path is a draft generator, not a source of truth. Its output must pass
schema validation, evidence grounding, raw-leak checks, answer-leak gates, and
summary fidelity checks. Failures fall back to the rule-based generator by
default and are reported through `generator_used` and
`generator_fallback_reason`.

## PHOTON / MLX

PHOTON/MLX support is optional.

Current state:

- The default sidecar uses deterministic summary generation and deterministic
  context admission.
- `PHOTON_SUMMARY_GENERATOR=llm` enables an opt-in MLX-backed local LLM draft
  summary path.
- `PHOTON_ACTION_MEMORY_CHECKPOINT=/path/to/checkpoint` is supported by the
  `ActionMemoryPhotonScorer` factory for local scorer evaluation.
- The committed checkpoint under
  `tests/fixtures/photon/checkpoints/action_memory_tiny/` is a tiny CI fixture,
  not a production model.
- Wiring a trained PHOTON checkpoint into live `/v1/context/pack` ranking is a
  follow-up task; the checkpoint path and fallback behavior are already covered
  by focused tests.

Install MLX extras only when working on optional local model paths:

```bash
python -m pip install -e ".[dev,mlx]"
```

## Inputs

Typical inputs include:

- user task
- conversation summary
- current working memory
- changed files
- repository metadata
- recent tool calls
- search results
- file reads
- test/build output
- previous similar sessions

## Outputs

Typical outputs include:

- action summaries
- context packs
- next action candidates
- target file candidates
- search query candidates
- command/test candidates
- evidence references and selected snippets
- avoid/retry guidance
- confidence, validation, and admission metadata

## Non-goals

PHOTON Action Memory is not intended to replace:

- the main coding agent
- the final-answer LLM
- a vector database
- a document RAG pipeline
- a general user memory system
- an agent runtime or orchestration framework

It is a focused memory controller for coding-agent behavior.

## Development

Requirements:

- Python 3.12
- `pip`

Install local development dependencies:

```bash
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

Run the standard checks:

```bash
ruff format --check .
ruff check .
mypy photon_action_memory tests
pytest -q
python -m build
```

Run the sidecar locally:

```bash
python -m uvicorn photon_action_memory.api.server:app \
  --host 127.0.0.1 \
  --port 18765
```

Smoke-check health:

```bash
curl -fsS http://127.0.0.1:18765/health
```

## Release

Releases are tagged as `vX.Y.Z`. Pushing a release tag triggers the GitHub
Actions release workflow, builds the Python source distribution and wheel, and
attaches the generated artifacts to a GitHub Release.

Use the repository release command when preparing a new release:

```text
/release patch
/release minor
/release major
/release 1.2.3
```

The release flow updates `pyproject.toml`, `photon_action_memory/__init__.py`,
and `CHANGELOG.md`, opens a release PR to `main`, and creates the tag only
after the PR is merged.

## License

PHOTON Action Memory is released under the MIT License. See `LICENSE`.
