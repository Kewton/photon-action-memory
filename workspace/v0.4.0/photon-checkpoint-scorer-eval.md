# PHOTON Checkpoint Scorer Evaluation

Issue #123 adds a tiny Action Memory PHOTON runtime checkpoint so the
`PhotonMLXActionMemoryScorer` path can be tested without network access or a
large model artifact.

## Fixture

Checkpoint:

```text
tests/fixtures/photon/checkpoints/action_memory_tiny/
```

Runtime state:

```json
{
  "bias": 0.1,
  "action_weights": {
    "summary": 0.15,
    "next_hint": 0.12,
    "failed_attempt": 0.2
  },
  "file_weights": {
    "SessionStore retrieval bug fix summary": 0.55,
    "tests/test_session_store.py": 0.35
  },
  "evidence_weights": {
    "evt_session_failure": 0.45,
    "SessionStore failure traceback": 0.4
  }
}
```

`weights.npz` is a tiny placeholder fixture. It is intentionally not a
production model weight file.

## Ranking Difference

Task:

```text
SessionStore retrieval bug
```

Candidate summaries:

| Candidate | Deterministic score | PHOTON fixture score | Notes |
|---|---:|---:|---|
| `SessionStore retrieval bug fix summary` | 0.65 | 0.80 | PHOTON adds learned `summary` and exact summary weight |
| `unrelated docs update` | 0.00 | 0.25 | PHOTON fixture leaves a low global summary prior |

Candidate evidence:

| Candidate | PHOTON fixture score | Notes |
|---|---:|---|
| `SessionStore failure traceback` | 0.50 | `bias + evidence_weights[text]` |

The important property is not the absolute score. It is that a checkpoint can
encode Action Memory specific priors that lexical overlap cannot represent,
while the sidecar keeps deterministic fallback when the checkpoint is missing,
invalid, or unavailable.

## Verification

Focused tests:

```bash
python -m pytest \
  tests/test_action_memory_checkpoint_builder.py \
  tests/test_action_memory_scorer.py \
  tests/test_photon_adapter.py \
  tests/test_checkpoint.py \
  -q
```

Expected result:

```text
28 passed
```

Type and lint:

```bash
python -m mypy photon_action_memory \
  tests/test_action_memory_checkpoint_builder.py \
  tests/test_action_memory_scorer.py \
  tests/test_photon_adapter.py \
  tests/test_checkpoint.py

python -m ruff check \
  photon_action_memory/models/checkpoint_builder.py \
  photon_action_memory/models/photon_adapter.py \
  photon_action_memory/models/photon_scorer.py \
  tests/test_action_memory_checkpoint_builder.py \
  tests/test_action_memory_scorer.py \
  scripts/build_action_memory_checkpoint.py
```

Both checks pass.

## Follow-up

This issue proves the checkpoint path and scorer behavior with a tiny fixture.
Production ranking still needs a separate task to train or derive weights from
larger eval/adoption logs and then wire the scorer into `/v1/context/pack`
ranking.
