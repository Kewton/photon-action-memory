"""Aggregate-only metrics hooks for local LLM evaluation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import ceil
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

LOCAL_LLM_REPORT_SCHEMA: str = "local-llm-metrics.v1"


class LocalLLMModelMeta(BaseModel):
    """Model metadata describing the local LLM under evaluation."""

    model_config = ConfigDict(extra="ignore")

    model_size_b: float | None = None
    quantization: str | None = None
    context_length: int | None = None
    backend: str | None = None


class LocalLLMRecord(BaseModel):
    """Per-turn local LLM performance measurements.

    All optional fields default to ``None``; absent fields are excluded from
    aggregate percentiles without affecting other metrics or breaking the runner.
    Raw prompts and tool outputs are never part of this schema.
    """

    model_config = ConfigDict(extra="ignore")

    prompt_tokens_per_turn: int = Field(default=0, ge=0)
    context_pack_tokens: int = Field(default=0, ge=0)
    prefill_time_ms: float | None = Field(default=None, ge=0)
    decode_tokens_per_second: float | None = Field(default=None, ge=0)
    peak_vram_mb: float | None = Field(default=None, ge=0)
    context_length_used: int | None = Field(default=None, ge=0)
    cpu_fallback_occurred: bool = False


class LocalLLMReport(BaseModel):
    """Aggregate-only local LLM metrics report.

    All values are totals, averages, or percentiles across the input records.
    No raw logs, prompts, or tool outputs are included.
    """

    schema_version: Literal["local-llm-metrics.v1"] = "local-llm-metrics.v1"
    total_records: int
    model_meta: LocalLLMModelMeta | None
    total_prompt_tokens: int
    avg_prompt_tokens_per_turn: float
    total_context_pack_tokens: int
    avg_context_pack_tokens_per_turn: float
    prefill_time_ms_p50: float | None
    prefill_time_ms_p95: float | None
    decode_tokens_per_second_p50: float | None
    decode_tokens_per_second_p95: float | None
    peak_vram_mb_p50: float | None
    peak_vram_mb_p95: float | None
    cpu_fallback_rate: float
    context_length_used_p50: float | None
    context_length_used_p95: float | None


RawLocalLLMRecord = LocalLLMRecord | Mapping[str, Any]


def build_local_llm_report(
    records: Sequence[RawLocalLLMRecord],
    *,
    model_meta: LocalLLMModelMeta | Mapping[str, Any] | None = None,
) -> LocalLLMReport:
    """Build an aggregate local LLM metrics report from per-turn records.

    All optional per-turn fields are excluded from aggregate computation when
    absent; missing fields never raise errors or distort other metrics.
    """
    parsed = [_coerce_record(r) for r in records]

    coerced_meta: LocalLLMModelMeta | None = None
    if model_meta is not None:
        if isinstance(model_meta, LocalLLMModelMeta):
            coerced_meta = model_meta
        else:
            coerced_meta = LocalLLMModelMeta.model_validate(model_meta)

    total_prompt_tokens = sum(r.prompt_tokens_per_turn for r in parsed)
    total_context_pack_tokens = sum(r.context_pack_tokens for r in parsed)

    prefill_times = sorted(
        float(r.prefill_time_ms) for r in parsed if r.prefill_time_ms is not None
    )
    decode_speeds = sorted(
        float(r.decode_tokens_per_second) for r in parsed if r.decode_tokens_per_second is not None
    )
    vram_values = sorted(float(r.peak_vram_mb) for r in parsed if r.peak_vram_mb is not None)
    context_lengths = sorted(
        float(r.context_length_used) for r in parsed if r.context_length_used is not None
    )

    cpu_fallback_count = sum(1 for r in parsed if r.cpu_fallback_occurred)

    return LocalLLMReport(
        total_records=len(parsed),
        model_meta=coerced_meta,
        total_prompt_tokens=total_prompt_tokens,
        avg_prompt_tokens_per_turn=_avg(total_prompt_tokens, len(parsed)),
        total_context_pack_tokens=total_context_pack_tokens,
        avg_context_pack_tokens_per_turn=_avg(total_context_pack_tokens, len(parsed)),
        prefill_time_ms_p50=_percentile(prefill_times, 50),
        prefill_time_ms_p95=_percentile(prefill_times, 95),
        decode_tokens_per_second_p50=_percentile(decode_speeds, 50),
        decode_tokens_per_second_p95=_percentile(decode_speeds, 95),
        peak_vram_mb_p50=_percentile(vram_values, 50),
        peak_vram_mb_p95=_percentile(vram_values, 95),
        cpu_fallback_rate=_rate(cpu_fallback_count, len(parsed)),
        context_length_used_p50=_percentile(context_lengths, 50),
        context_length_used_p95=_percentile(context_lengths, 95),
    )


def _coerce_record(record: RawLocalLLMRecord) -> LocalLLMRecord:
    if isinstance(record, LocalLLMRecord):
        return record
    return LocalLLMRecord.model_validate(record)


def _avg(total: int, count: int) -> float:
    if count == 0:
        return 0.0
    return total / count


def _rate(count: int, total: int) -> float:
    if total == 0:
        return 0.0
    return count / total


def _percentile(sorted_values: Sequence[float], percentile: int) -> float | None:
    if not sorted_values:
        return None
    index = max(0, ceil((percentile / 100) * len(sorted_values)) - 1)
    return sorted_values[index]


__all__ = [
    "LOCAL_LLM_REPORT_SCHEMA",
    "LocalLLMModelMeta",
    "LocalLLMRecord",
    "LocalLLMReport",
    "build_local_llm_report",
]
