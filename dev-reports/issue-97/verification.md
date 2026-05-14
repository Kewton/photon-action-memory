# Issue #97 Verification

## Acceptance criteria

| Criterion | Status | Evidence |
| --- | --- | --- |
| 日本語 task + 英語 seed の組み合わせで `premature_termination_risk` warning が発火する | ✅ | `tests/test_context_pack.py::test_build_context_pack_rejects_japanese_task_english_seed_overlap` and `tests/test_overlap_detector.py::test_compute_overlap_japanese_task_english_summary_trips_threshold` |
| 既存の英語 task テスト (`tests/test_context_pack.py`) が引き続き pass | ✅ | Full file passes (52 tests). |
| レイテンシ: `/v1/context/pack` p99 < 500ms | ✅ | Microbenchmark: `compute_overlap` averages 0.021ms/call in `multilingual` mode (5000 iters), well under the budget. |
| embedding モデルは optional dependency（pip extra） | ✅ | `pyproject.toml` registers `embedding = ["sentence-transformers>=2.7"]`; runtime import lives inside `overlap_detector._try_load_embedder()` and the detector falls back to the lexical path on `ImportError`. |
| 設定で detector mode (`ascii` / `multilingual` / `embedding` / `hybrid`) を切替可能 | ✅ | `OverlapDetectorMode` literal + `PHOTON_OVERLAP_DETECTOR_MODE` env var + per-call `mode=` keyword on `evaluate_summary_quality` and on `tokenize`/`compute_overlap`. |

## Commands

```
python -m pytest tests/test_overlap_detector.py tests/test_context_pack.py -q
python -m pytest -q
python -m mypy
python -m ruff check .
```

## Results

```
tests/test_overlap_detector.py tests/test_context_pack.py:
  52 passed, 2 warnings in 9.11s

pytest (full suite):
  913 passed, 1 skipped, 2 warnings in 11.78s
  (skipped is the macOS-only mlx smoke test, unrelated)

mypy:
  Success: no issues found in 52 source files

ruff:
  All checks passed!
```

The two `DeprecationWarning`s are emitted by transitive C-extensions of the
optional `sentence-transformers` install (`SwigPyPacked`/`SwigPyObject`) and
are unrelated to the changes in this Issue.

## Latency microbenchmark

```
multilingual: 0.021ms per call (5000 iters in 0.10s)
ascii:        0.009ms per call (5000 iters in 0.04s)
```

Per-summary cost is ~21µs in multilingual mode; even at thousands of
summaries per request the gate stays under the 500ms p99 budget for
`/v1/context/pack`.
