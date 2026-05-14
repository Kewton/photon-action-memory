# Issue #97 Implementation Summary

## Changes

### New module: `photon_action_memory/context/overlap_detector.py`

Centralises task↔summary tokenization and overlap computation behind a
mode-aware API. Public surface:

- `OverlapDetectorMode` literal (`ascii | multilingual | embedding | hybrid`).
- `OverlapResult` dataclass — carries `overlap`, `novel`, token counts, and
  effective mode.
- `get_default_overlap_mode()` — reads `PHOTON_OVERLAP_DETECTOR_MODE`,
  defaults to `multilingual`, falls back with a warning on unknown values.
- `tokenize(text, *, mode)` — Latin tokens for `ascii`; Latin tokens +
  CJK character bigrams + JP→canonical-EN bridge for the other modes.
- `compute_overlap(summary_text, task_text, *, mode)` — lexical overlap for
  `ascii`/`multilingual`; lexical+semantic for `embedding`/`hybrid`,
  with safe fallback when `sentence-transformers` is not installed or fails
  to encode.

The JP→canonical-EN dictionary covers the verbs and nouns that dominate
coding-task vocabulary (e.g. `追加`→`add`, `作成`→`create`, `検証`→`verify`,
`ボタン`→`button`, `ページ`→`page`, `要素`→`element`,
`インタラクティブ`→`interactive`). Unknown CJK runs still contribute via
character bigrams so the detector degrades gracefully outside the
dictionary's coverage.

### Update: `photon_action_memory/context/quality_gate.py`

- Replaced the local `_TOKEN_RE`/`_STOPWORDS`/`_tokens` with calls into the
  new detector.
- `evaluate_summary_quality()` now accepts an optional `mode` keyword;
  `None` resolves to the configured default. All thresholds
  (`overlap >= 0.50`, `novel <= 0.50`, `premature overlap >= 0.35`,
  `shortcut overlap >= 0.30`) and warning messages are unchanged, so the
  decision contract is preserved.
- `_has_premature_termination_risk()` is rewritten in terms of
  `tokenize(hint_text, mode=mode)` so cross-lingual hints get the same
  treatment.

### Tests

- `tests/test_context_pack.py`: added
  `test_build_context_pack_rejects_japanese_task_english_seed_overlap`
  covering the acceptance criterion — Japanese task + English seed must
  trip `premature_termination_risk` and produce a `deny` decision plus the
  `summary_quality_gate` warning.
- `tests/test_overlap_detector.py` (new): unit coverage for default-mode
  resolution, ASCII parity, JP→EN bridging, CJK bigram fallback,
  cross-lingual overlap threshold, and the graceful embedding-mode fallback
  when the optional extra is absent.

### Packaging

- `pyproject.toml`: registered `embedding = ["sentence-transformers>=2.7"]`
  optional dependency. Base install is unchanged.

## Behaviour

- **Default mode (`multilingual`)** is a strict superset of `ascii` for
  Latin-only inputs — all existing English-task tests still pass without
  edits.
- Setting `PHOTON_OVERLAP_DETECTOR_MODE=ascii` restores the legacy
  behaviour bit-for-bit (verified by
  `test_compute_overlap_ascii_mode_misses_cross_lingual_overlap`).
- Setting the mode to `embedding` or `hybrid` enables the semantic path;
  with `sentence-transformers` installed the detector returns the higher of
  lexical and cosine-mapped similarity for `hybrid`, or the cosine value
  for `embedding`. Without the extra, both modes fall back to the lexical
  multilingual signal so the quality gate stays useful.

## Not changed

- `photon_action_memory/eval/summary_fidelity.py` and
  `photon_action_memory/training/labels.py` were listed as suspected files
  but their tokenizers target evidence/code-identifier extraction, not
  natural-language task overlap. Touching them would have broadened the
  blast radius without serving the cross-lingual-overlap goal, so they are
  intentionally left alone (called out in `design.md`).
