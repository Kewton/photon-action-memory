# Issue #44 – Add Local LLM Metrics Hooks: Implementation Summary

## What Was Built

### `photon_action_memory/eval/local_llm.py` (new)

Implements five public symbols exported via `__all__`:

**`LOCAL_LLM_REPORT_SCHEMA`** – Schema version string `"local-llm-metrics.v1"`.

**`LocalLLMModelMeta`** – Pydantic model for model-level metadata passed to the report. All fields optional; extra fields silently ignored.

| Field | Type | Description |
|---|---|---|
| `model_size_b` | `float \| None` | Model size in billions of parameters |
| `quantization` | `str \| None` | Quantization scheme (e.g. `"q4_0"`, `"q8_0"`, `"f16"`) |
| `context_length` | `int \| None` | Maximum context length in tokens |
| `backend` | `str \| None` | Inference backend (e.g. `"mlx"`, `"llama.cpp"`, `"ollama"`) |

**`LocalLLMRecord`** – Pydantic model for per-turn local LLM performance measurements. Extra fields are silently ignored (`extra="ignore"`) so raw prompts and tool outputs in caller dicts never reach the record.

| Field | Type | Description |
|---|---|---|
| `prompt_tokens_per_turn` | `int` | Tokens in the prompt for this turn (required, default 0) |
| `context_pack_tokens` | `int` | Tokens in the admitted ContextPack (required, default 0) |
| `prefill_time_ms` | `float \| None` | TTFT / prefill latency in milliseconds |
| `decode_tokens_per_second` | `float \| None` | Decoding throughput in tokens per second |
| `peak_vram_mb` | `float \| None` | Peak GPU VRAM usage in megabytes |
| `context_length_used` | `int \| None` | Actual context length consumed this turn |
| `cpu_fallback_occurred` | `bool` | Whether any computation fell back to CPU |

**`LocalLLMReport`** – Aggregate-only Pydantic report. Contains no raw records, prompts, or tool outputs.

| Field | Type | Description |
|---|---|---|
| `schema_version` | literal | `"local-llm-metrics.v1"` |
| `total_records` | `int` | Number of input records |
| `model_meta` | `LocalLLMModelMeta \| None` | Forwarded from caller |
| `total_prompt_tokens` | `int` | Sum of `prompt_tokens_per_turn` |
| `avg_prompt_tokens_per_turn` | `float` | Mean prompt tokens; `0.0` on empty |
| `total_context_pack_tokens` | `int` | Sum of `context_pack_tokens` |
| `avg_context_pack_tokens_per_turn` | `float` | Mean context pack tokens; `0.0` on empty |
| `prefill_time_ms_p50` | `float \| None` | p50 of records with `prefill_time_ms` set |
| `prefill_time_ms_p95` | `float \| None` | p95 of records with `prefill_time_ms` set |
| `decode_tokens_per_second_p50` | `float \| None` | p50 decode throughput |
| `decode_tokens_per_second_p95` | `float \| None` | p95 decode throughput |
| `peak_vram_mb_p50` | `float \| None` | p50 peak VRAM |
| `peak_vram_mb_p95` | `float \| None` | p95 peak VRAM |
| `cpu_fallback_rate` | `float` | Fraction of turns with CPU fallback; `0.0` on empty |
| `context_length_used_p50` | `float \| None` | p50 context length used |
| `context_length_used_p95` | `float \| None` | p95 context length used |

Optional-metric percentiles are `None` when no record in the input provides that field. They never distort the remaining metrics.

**`build_local_llm_report(records, *, model_meta=None)`** – Aggregates a `Sequence[LocalLLMRecord | Mapping[str, Any]]` into a `LocalLLMReport`. Dict records are coerced via `model_validate`; unknown fields are dropped.

### `photon_action_memory/eval/runner.py` (modified)

Added three runner functions following the existing `run_eval` / `run_fixture` / `write_metrics_report` pattern:

- **`run_local_llm(records, *, model_meta, output_path)`** – Run over an iterable and optionally write JSON.
- **`run_local_llm_fixture(fixture_path, *, model_meta, output_path)`** – Load from a JSON list or `{"records": [...]}` file and run.
- **`write_local_llm_report(report, output_path)`** – Write aggregate JSON; creates parent directories.

### `photon_action_memory/eval/__init__.py` (modified)

Added imports and `__all__` entries for:
- `LOCAL_LLM_REPORT_SCHEMA`
- `LocalLLMModelMeta`
- `LocalLLMRecord`
- `LocalLLMReport`
- `build_local_llm_report`
- `run_local_llm`
- `run_local_llm_fixture`
- `write_local_llm_report`

### `tests/test_local_llm_metrics.py` (new)

32 focused tests covering:

- Empty records produce all-zero / all-None aggregate fields.
- Single record with required fields only.
- Prompt tokens and context pack tokens summed and averaged.
- `prefill_time_ms` p50/p95 with full, absent, and partial records.
- `decode_tokens_per_second` p50/p95 with full and absent data.
- `peak_vram_mb` p50/p95 with full and absent data.
- `context_length_used` p50/p95 with full and absent data.
- `cpu_fallback_rate` at 0%, 50%, and 100%.
- `model_meta` accepted as `LocalLLMModelMeta`, partial dict, full dict, or dict with unknown fields.
- Schema version constant and report field.
- Report JSON excludes raw fields (`prompt`, `raw`, `records`, `cpu_fallback_occurred`).
- Extra dict fields in records are silently ignored.
- All optional metrics absent → all percentile fields are `None`.
- Runner returns `LocalLLMReport` instance.
- Runner writes aggregate JSON; raw keys absent from output.
- Fixture loading from JSON list and `{"records": [...]}` object.
- Fixture runner forwards `model_meta`.
- `write_local_llm_report` creates missing parent directories.

## Design Decisions

**Pydantic for both `LocalLLMRecord` and `LocalLLMModelMeta`.** Unlike `PollutionRecord` (dataclass), `LocalLLMRecord` is expected to come from JSON fixtures as well as programmatic construction. Pydantic's `model_validate` handles both paths with `extra="ignore"`, which is the primary guard ensuring raw prompts never appear in records.

**Optional metrics use `None` sentinel, not 0.** A `prefill_time_ms` of `None` means "not measured this turn", which is structurally distinct from a measured value of `0 ms`. Using `None` lets the aggregator exclude absent records from percentile computation without distorting the result.

**`cpu_fallback_occurred: bool` in record → `cpu_fallback_rate: float` in report.** Per-turn CPU fallback is a binary event. The aggregate rate is more useful for comparing backends or quantization schemes and is the format requested in the issue.

**Percentile implementation is ceiling-indexed (same as `metrics.py`).** Consistent with the existing `_percentile` helper; returns an actual observed value rather than an interpolated one.

**`model_meta` is caller-supplied, not per-record.** Model configuration (size, quantization, backend) is constant across all turns in a single eval run, so it is passed once to `build_local_llm_report` rather than repeated in every record.

**Averages return `0.0` on empty input.** Consistent with the `_rate` helper pattern used throughout the eval package.
