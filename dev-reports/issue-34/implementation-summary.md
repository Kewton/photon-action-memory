# Issue 34 Implementation Summary: ActionChunker

## Files Added

| File | Purpose |
|------|---------|
| `photon_action_memory/memory/chunks.py` | `ActionChunker` class and helper functions |
| `tests/test_chunks.py` | 66 tests covering all acceptance criteria |

## Public API

```python
from photon_action_memory.memory.chunks import ActionChunker

chunker = ActionChunker()

# Group by (session_id, turn_id) - one ActionChunk per pair
chunks: list[ActionChunk] = chunker.chunk(events)

# Collapse all events into one ActionChunk (ignores turn boundaries)
chunk: ActionChunk = chunker.chunk_one(events)
```

## Key Decisions

**Grouping by turn_id:** The turn is the natural unit of agent action. All events
within a turn share the same intent and context, making turn-level grouping the
correct default without requiring semantic analysis.

**Deterministic chunk_id:** SHA-256 of sorted event IDs ensures reproducibility.
The same events always produce the same chunk regardless of call order or insertion
sequence.

**No sanitization in chunker:** `EventStore.append_event()` sanitizes before
storage. The chunker consumes only `StoredEvent` objects, so sanitization is
already guaranteed. Running it again in the chunker would be redundant and could
corrupt already-normalized content.

**Inference over configuration:** Kind, outcome, and risk are inferred from event
metadata rather than requiring callers to pass them explicitly. This keeps the API
minimal while still covering the schema fields.

## Acceptance Criteria Mapping

| Criterion | Implementation |
|-----------|---------------|
| Recent EventRecords grouped into ActionChunk | `ActionChunker.chunk()` groups by `(session_id, turn_id)` |
| Chunk keeps source event IDs | `ActionChunk.event_ids` preserves insertion order |
| Kind / outcome / risk representable | `_infer_kind`, `_infer_outcome`, `_infer_risk` helpers |
| Only sanitized events used | Accepts `StoredEvent` only; EventStore guarantees sanitization |
| Deterministic fallback | `_deterministic_chunk_id` hashes sorted event IDs via SHA-256 |
