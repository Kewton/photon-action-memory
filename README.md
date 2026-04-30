# PHOTON Action Memory

Action-oriented memory layer for coding agents, powered by PHOTON.

PHOTON Action Memory is a local-first memory controller for coding agents. It learns from tool loops, repository exploration, test results, and past agent sessions to help agents choose the next file, command, evidence, or action.

## Positioning

Most memory systems for AI agents focus on storing and retrieving facts:

- user preferences
- past conversations
- documents
- knowledge graphs
- embeddings over large corpora

PHOTON Action Memory focuses on a narrower problem:

> Given the current coding task, repository state, recent tool results, and past sessions, what should the agent do next?

It is designed as an action memory layer, not a general-purpose RAG system.

## Why

Coding agents spend a large amount of time on repeated exploration:

- searching for the same symbols
- reopening the same files
- retrying failed commands
- missing useful tests
- drifting away from the original task
- losing context between sessions

PHOTON Action Memory aims to reduce that waste by turning past agent behavior into reusable action guidance.

## Memory Hierarchy

PHOTON Action Memory is intended to sit between short-lived working memory and long-term knowledge stores.

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

In this model, PHOTON Action Memory acts like an L3 action cache for coding agents.

## Core Capabilities

- Predict useful next actions: read, search, edit, test, build, inspect, ask, or answer.
- Recommend files, symbols, commands, and tests based on current task state.
- Select evidence that should be included in the agent context.
- Reuse successful patterns from similar past sessions.
- Detect repeated failed attempts and suggest alternatives.
- Warn when the current plan drifts away from the original task.
- Adapt to repository-specific workflows over time.

## Target Integrations

The first target integration is Anvil, a local-first coding agent.

The intended deployment model is a fail-open local sidecar:

```text
Coding Agent
  ↓
PHOTON Action Memory Sidecar
  ↓
Local Event Store / Memory Index
  ↓
PHOTON Model
```

The agent remains responsible for final decisions and tool execution. PHOTON Action Memory provides ranked suggestions and compact memory signals.

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

- next action candidates
- target file candidates
- search query candidates
- command/test candidates
- relevant evidence snippets
- similar prior cases
- avoid/retry guidance
- confidence and rationale metadata

## Training Data

PHOTON Action Memory is trained from coding-agent trajectories rather than final assistant prose.

Useful training examples include:

- task state to next action
- task state to target files
- tool result to next command
- error output to relevant evidence
- failed attempt to avoid signal
- session history to compact working memory
- final outcome to trajectory quality

The goal is not to imitate a large language model's writing style. The goal is to improve action selection inside coding-agent loops.

## Non-goals

PHOTON Action Memory is not intended to replace:

- the main coding agent
- the final-answer LLM
- a vector database
- a document RAG pipeline
- a general user memory system
- an agent runtime or orchestration framework

It is a focused memory controller for coding-agent behavior.

## Related Systems

PHOTON Action Memory is complementary to existing memory and agent infrastructure:

- Mem0: user and personalization memory
- Zep: temporal conversation and graph memory
- Letta: stateful agent runtime and memory blocks
- Cognee: knowledge graph and RAG over documents/data

PHOTON Action Memory focuses specifically on action-oriented memory for coding agents.

## Roadmap

- Define the sidecar request/response schema.
- Build a local sidecar API for agent integrations.
- Add an offline dataset exporter for coding-agent logs.
- Train action, file, evidence, and failure-avoidance heads.
- Integrate with Anvil's repo context and working memory.
- Add shadow-mode evaluation.
- Measure reduction in repeated exploration and tool calls.
- Add repository-local adaptation.
- Provide MCP / stdio adapters for broader agent compatibility.

## Status

This repository is in the initial design and implementation phase.

The v0.1.0 development bootstrap is organized under `workspace/v0.1.0/`.

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

PHOTON / MLX support is optional during v0.1.0 bootstrap:

```bash
python -m pip install -e ".[dev,mlx]"
```

The package must continue to import and run its default tests without MLX installed.
