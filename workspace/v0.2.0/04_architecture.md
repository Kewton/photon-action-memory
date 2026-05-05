# 04. Architecture

## 1. Logical Architecture

```
Coding Agent
├── executes tools
├── sends sanitized events
├── asks for suggestions
├── asks for context pack before LLM call
└── expands evidence only when needed
        ↓
PHOTON Action Memory Sidecar
├── API Layer
├── Schema Validator
├── Sanitizer
├── Event Store
├── Action Chunker
├── Action Summary Builder
├── Summary Canonicalizer
├── Staleness Guard
├── Context Admission Controller
├── Token Budget Manager
├── Evidence Expander
├── Candidate Retriever
├── PHOTON Model Adapter
├── Action Ranker
├── Context Ranker
├── Summary Fidelity Checker
└── Eval Logger
        ↓
Local State
├── events.sqlite
├── action_chunks.jsonl
├── action_summaries.jsonl
├── evidence_refs.jsonl
├── context_packs.jsonl
├── cases.jsonl
├── eval_runs/
└── model_cache/
```

## 2. Main Data Flow

### Tool result ingestion

1. Agent executes tool.
2. Agent sends result to `POST /v1/events`.
3. Sidecar validates schema.
4. Sanitizer redacts secret / token / private path / control chars.
5. Sanitized event is stored in `events.sqlite`.
6. Event is linked to `session_id`, `turn_id`, `repo_id`, `commit`.

### Action chunking

1. Recent events are grouped by intent / turn / time / tool type.
2. Sidecar creates ActionChunk.
3. ActionChunk records `event_ids` and coarse outcome.
4. Chunk is stored in `action_chunks.jsonl` or SQLite table.

### Summary update

1. ActionChunk is converted into ActionSummary.
2. Facts, hypotheses, failed attempts, avoid guidance are separated.
3. Every fact-like statement receives `evidence_ids`.
4. Summary is validated.
5. Summary is stored as compact action state.

### Prompt construction

1. Before next LLM call, agent calls `POST /v1/context/pack`.
2. Context Admission Controller selects prompt-visible items.
3. Raw tool output is denied by default.
4. Token Budget Manager enforces `max_memory_tokens`.
5. ContextPack is returned.
6. Agent inserts ContextPack into prompt.

### Evidence expansion

1. If agent needs detail, it calls `POST /v1/evidence/expand`.
2. Evidence Expander retrieves local event detail.
3. Sanitizer runs again.
4. Only selected snippet is returned.
5. Expansion decision is logged.

## 3. PHOTON-style Hierarchy

v0.2.0 uses a hierarchy of action states.

```
Raw Event
  ↓
ActionChunk
  ↓
ActionSummary
  ↓
SessionActionState
  ↓
ContextPack
  ↓
LLM Prompt
```

Details are available only through the reverse path.

```
LLM asks for detail
  ↓
evidence_id
  ↓
EvidenceRef
  ↓
selected sanitized snippet
```

## 4. Recursive State Update

v0.2.0 should avoid re-summarizing the entire session on every turn.

Preferred update:

```
S_t = update(S_{t-1}, ActionChunk_t)
```

Where:

- `S_t` — current SessionActionState
- `S_{t-1}` — previous SessionActionState
- `ActionChunk_t` — new action chunk produced by recent tool events

This supports long-running sessions because the sidecar updates compact state incrementally.

## 5. Context Admission Controller

The Context Admission Controller decides whether each memory item should enter the prompt.

**Inputs:**

- task summary
- working memory
- recent events
- ActionSummary candidates
- EvidenceRef candidates
- previous ContextPack
- token budget
- admission policy
- staleness status

**Outputs:**

- `admit`
- `omit`
- `expand`
- `defer`
- `deny`

**Decision factors:**

- relevance to current task
- recency
- evidence grounding
- staleness
- risk
- token cost
- duplication with already admitted context
- whether detail is needed
- whether summary is sufficient

## 6. Evidence Expander

Evidence Expander is the only path from summary to detail.

Rules:

- full raw output is denied by default
- sanitizer runs again before returning text
- selected snippets are preferred
- `max_expand_chars` must be enforced
- command output should be summarized if too long
- line ranges should be included when available

## 7. Staleness Guard

Summary and evidence can become stale.

**Staleness triggers:**

- commit hash changed
- referenced file changed
- referenced line range changed
- branch changed
- task signature changed
- test command result contradicted by later event
- summary contradicted by newer evidence

**Staleness status:**

```
valid
stale
partial
contradicted
unknown
```

Stale summaries are denied by default unless explicitly requested for historical context.

## 8. Deterministic Fallback

PHOTON model is optional.

When model is unavailable:

- context pack still works
- ranking uses deterministic heuristics
- evidence expansion still works
- summary validation still works
- sidecar remains useful

**Fallback heuristics:**

- recent successful search results are useful
- repeated identical search/read is less useful
- failed command without file change should be avoided
- exact error-linked files rank high
- touched files rank high
- stale summaries are omitted
- facts with evidence rank above ungrounded statements

## 9. Package Structure

```
photon_action_memory/
├── api/
│   ├── schema.py
│   ├── server.py
│   └── client.py
├── memory/
│   ├── store.py
│   ├── sanitizer.py
│   ├── compaction.py
│   ├── chunks.py
│   ├── summaries.py
│   ├── evidence.py
│   └── staleness.py
├── context/
│   ├── admission.py
│   ├── budget.py
│   ├── pack.py
│   ├── policies.py
│   └── render.py
├── ranking/
│   ├── candidates.py
│   ├── fallback.py
│   ├── ranker.py
│   └── context_ranker.py
├── models/
│   ├── photon_adapter.py
│   ├── state.py
│   ├── checkpoint.py
│   └── context_scorer.py
├── eval/
│   ├── metrics.py
│   ├── runner.py
│   ├── pollution.py
│   ├── summary_fidelity.py
│   └── local_llm.py
└── training/
    ├── exporters/
    ├── labels.py
    ├── datasets.py
    └── train.py
```

## 10. Anvil Integration Flow

1. Anvil executes a tool.
2. Anvil sends sanitized event to PHOTON Action Memory.
3. Sidecar stores event locally.
4. Sidecar updates ActionChunk / ActionSummary.
5. Before next LLM call, Anvil calls `POST /v1/context/pack`.
6. Anvil inserts ContextPack into prompt.
7. Anvil calls `POST /v1/suggest` if next action guidance is needed.
8. If exact detail is needed, Anvil calls `POST /v1/evidence/expand`.
9. Anvil logs adoption / ignored / outcome through `POST /v1/evaluate`.

## 11. Prompt Rendering

ContextPack should be rendered compactly.

Example:

```
## Action Memory
Task:
- Fix failing session persistence test.
Done:
- Searched SessionStore and found primary implementation in src/session/store.rs. [evt_041]
- Ran cargo test session_persistence; failure reproduced as serialization mismatch. [evt_052]
Facts:
- SessionStore implementation is in src/session/store.rs. [evt_041]
Open hypotheses:
- serde path may be involved, but this is not confirmed. [evt_052]
Avoid:
- Do not rerun repo-wide grep for SessionStore unless files changed. [evt_041]
Next useful actions:
- Read src/session/store.rs.
- Inspect tests/session_persistence.rs.
Evidence detail:
- Use evidence_id evt_052 only if the exact failure snippet is needed.
```

## 12. Security and Privacy

Security requirements:

- sanitizer runs before event store
- sanitizer runs again before evidence expansion
- raw secret-like strings are redacted
- absolute home paths are redacted
- token-like strings are redacted
- raw logs are not committed
- eval reports do not include per-turn raw logs
- exported datasets are sanitized
