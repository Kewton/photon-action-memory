# Issue #97 Design

## Goal

Extend `photon_action_memory/context/quality_gate.py` so that
`evaluate_summary_quality` detects task↔summary overlap for **cross-lingual**
combinations — most importantly Japanese tasks paired with English seeds (or
vice versa). The existing ASCII-only tokenizer (`_TOKEN_RE = r"[a-z0-9]+"`)
yields no signal for Japanese text, so cross-lingual overlap is invisible and
the `premature_termination_risk` warning never fires.

## Approach

Replace the single ASCII tokenizer with a small `overlap_detector` module that
implements four switchable modes:

1. **`ascii`** — current behaviour, kept for backward compatibility and
   parity testing.
2. **`multilingual`** — adds CJK character bigrams plus a small JP→canonical-EN
   keyword bridge for the verbs/nouns that dominate coding-task vocabulary
   (e.g. `追加`→`add`, `作成`→`create`, `検証`→`verify`, `ボタン`→`button`,
   `ページ`→`page`, `要素`→`element`, `インタラクティブ`→`interactive`).
3. **`embedding`** — optional, behind a pip extra. Uses a multilingual sentence
   embedder when installed; if the dependency is missing the detector logs a
   warning and **falls back to `multilingual`** so the quality gate stays
   functional.
4. **`hybrid`** — runs `multilingual` first; when an embedder is available the
   embedding similarity is taken as a max-of with the multilingual ratio so
   semantic overlap can still trip thresholds the lexical signal missed.

The detector exposes:

- `tokenize(text, *, mode)` → `set[str]`
- `compute_overlap(summary_text, task_text, *, mode)` → `OverlapResult`

`evaluate_summary_quality` is rewritten on top of `tokenize`, so the
existing decision rules (low-value overlap threshold, premature-termination
overlap threshold, meta-information allowlist, verification guidance) stay
exactly the same — only the **token vocabulary** widens.

## Mode selection

- API surface: `evaluate_summary_quality(summary, task_text, *, mode=None)`.
  `None` resolves to `get_default_overlap_mode()`.
- Runtime config: `get_default_overlap_mode()` reads
  `PHOTON_OVERLAP_DETECTOR_MODE`; default is `multilingual`.
  `multilingual` is a strict superset of `ascii` for Latin-only inputs, so
  promoting it to the default does not regress existing English seeds.

## Latency

- `ascii` / `multilingual` are pure regex + a small in-memory dict — sub-ms
  per summary, well within the `/v1/context/pack` p99 < 500ms target.
- `embedding` / `hybrid` lazy-import the embedder. The model is loaded on
  first use and reused for the process lifetime. When the embedder cannot be
  loaded (missing extra, model not cached), the detector reports it once via
  warning logging and falls back to the lexical path.

## Optional dependency

`pyproject.toml` gains:

```
[project.optional-dependencies]
embedding = ["sentence-transformers>=2.7"]
```

Install with `pip install photon-action-memory[embedding]`. The runtime
import lives inside the detector to keep the base install free of heavy
PyTorch deps.

## Scope

- New module: `photon_action_memory/context/overlap_detector.py`.
- Edit: `photon_action_memory/context/quality_gate.py` (use the new detector,
  accept `mode` parameter, no behavioural change for English seeds).
- Tests: add JP-task + EN-seed regression to `tests/test_context_pack.py`
  alongside the existing S2/S5 cases. Add focused detector unit coverage in
  `tests/test_overlap_detector.py` for tokenization and cross-lingual overlap.
- `pyproject.toml`: register the `embedding` extra.

## Out of scope

- Replacing the lexical signal in `summary_fidelity` (still ASCII-only by
  design — evidence text is generally tool output and we do not want to mix
  detector vocabulary with grounding semantics).
- Training-label tokenization in `photon_action_memory/training/labels.py`
  (code-identifier extraction; not a natural-language overlap problem).
