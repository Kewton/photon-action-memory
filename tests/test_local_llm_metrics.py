"""Tests for photon_action_memory.eval.local_llm."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from photon_action_memory.eval.local_llm import (
    LOCAL_LLM_REPORT_SCHEMA,
    LocalLLMModelMeta,
    LocalLLMRecord,
    LocalLLMReport,
    build_local_llm_report,
)
from photon_action_memory.eval.runner import (
    run_local_llm,
    run_local_llm_fixture,
    write_local_llm_report,
)

# ---------------------------------------------------------------------------
# Empty records
# ---------------------------------------------------------------------------


def test_empty_records_returns_zero_report() -> None:
    report = build_local_llm_report([])

    assert report.total_records == 0
    assert report.total_prompt_tokens == 0
    assert report.avg_prompt_tokens_per_turn == 0.0
    assert report.total_context_pack_tokens == 0
    assert report.avg_context_pack_tokens_per_turn == 0.0
    assert report.prefill_time_ms_p50 is None
    assert report.prefill_time_ms_p95 is None
    assert report.decode_tokens_per_second_p50 is None
    assert report.decode_tokens_per_second_p95 is None
    assert report.peak_vram_mb_p50 is None
    assert report.peak_vram_mb_p95 is None
    assert report.cpu_fallback_rate == 0.0
    assert report.context_length_used_p50 is None
    assert report.context_length_used_p95 is None
    assert report.model_meta is None


# ---------------------------------------------------------------------------
# Required fields: prompt_tokens_per_turn and context_pack_tokens
# ---------------------------------------------------------------------------


def test_single_record_required_only() -> None:
    report = build_local_llm_report(
        [LocalLLMRecord(prompt_tokens_per_turn=100, context_pack_tokens=50)]
    )

    assert report.total_records == 1
    assert report.total_prompt_tokens == 100
    assert report.avg_prompt_tokens_per_turn == 100.0
    assert report.total_context_pack_tokens == 50
    assert report.avg_context_pack_tokens_per_turn == 50.0
    assert report.cpu_fallback_rate == 0.0


def test_prompt_tokens_summed_and_averaged() -> None:
    records = [
        LocalLLMRecord(prompt_tokens_per_turn=100),
        LocalLLMRecord(prompt_tokens_per_turn=200),
        LocalLLMRecord(prompt_tokens_per_turn=300),
    ]
    report = build_local_llm_report(records)

    assert report.total_prompt_tokens == 600
    assert report.avg_prompt_tokens_per_turn == pytest.approx(200.0)


def test_context_pack_tokens_summed_and_averaged() -> None:
    records = [
        LocalLLMRecord(context_pack_tokens=40),
        LocalLLMRecord(context_pack_tokens=60),
    ]
    report = build_local_llm_report(records)

    assert report.total_context_pack_tokens == 100
    assert report.avg_context_pack_tokens_per_turn == 50.0


# ---------------------------------------------------------------------------
# Optional: prefill_time_ms percentiles
# ---------------------------------------------------------------------------


def test_prefill_time_percentiles() -> None:
    records = [
        LocalLLMRecord(prefill_time_ms=100.0),
        LocalLLMRecord(prefill_time_ms=200.0),
        LocalLLMRecord(prefill_time_ms=300.0),
        LocalLLMRecord(prefill_time_ms=400.0),
    ]
    report = build_local_llm_report(records)

    assert report.prefill_time_ms_p50 == 200.0
    assert report.prefill_time_ms_p95 == 400.0


def test_prefill_time_absent_gives_none() -> None:
    report = build_local_llm_report([LocalLLMRecord(), LocalLLMRecord()])

    assert report.prefill_time_ms_p50 is None
    assert report.prefill_time_ms_p95 is None


def test_partial_prefill_time_excludes_absent_records() -> None:
    records = [
        LocalLLMRecord(prefill_time_ms=100.0),
        LocalLLMRecord(),
        LocalLLMRecord(prefill_time_ms=300.0),
    ]
    report = build_local_llm_report(records)

    assert report.prefill_time_ms_p50 == 100.0
    assert report.prefill_time_ms_p95 == 300.0


# ---------------------------------------------------------------------------
# Optional: decode_tokens_per_second percentiles
# ---------------------------------------------------------------------------


def test_decode_throughput_percentiles() -> None:
    records = [
        LocalLLMRecord(decode_tokens_per_second=50.0),
        LocalLLMRecord(decode_tokens_per_second=100.0),
    ]
    report = build_local_llm_report(records)

    assert report.decode_tokens_per_second_p50 == 50.0
    assert report.decode_tokens_per_second_p95 == 100.0


def test_decode_throughput_absent_gives_none() -> None:
    report = build_local_llm_report([LocalLLMRecord()])

    assert report.decode_tokens_per_second_p50 is None
    assert report.decode_tokens_per_second_p95 is None


# ---------------------------------------------------------------------------
# Optional: peak_vram_mb percentiles
# ---------------------------------------------------------------------------


def test_peak_vram_percentiles() -> None:
    records = [
        LocalLLMRecord(peak_vram_mb=1024.0),
        LocalLLMRecord(peak_vram_mb=2048.0),
        LocalLLMRecord(peak_vram_mb=4096.0),
    ]
    report = build_local_llm_report(records)

    assert report.peak_vram_mb_p50 == 2048.0
    assert report.peak_vram_mb_p95 == 4096.0


def test_peak_vram_absent_gives_none() -> None:
    report = build_local_llm_report([LocalLLMRecord()])

    assert report.peak_vram_mb_p50 is None
    assert report.peak_vram_mb_p95 is None


# ---------------------------------------------------------------------------
# Optional: context_length_used percentiles
# ---------------------------------------------------------------------------


def test_context_length_used_percentiles() -> None:
    records = [
        LocalLLMRecord(context_length_used=1000),
        LocalLLMRecord(context_length_used=2000),
        LocalLLMRecord(context_length_used=3000),
    ]
    report = build_local_llm_report(records)

    assert report.context_length_used_p50 == 2000.0
    assert report.context_length_used_p95 == 3000.0


def test_context_length_used_absent_gives_none() -> None:
    report = build_local_llm_report([LocalLLMRecord()])

    assert report.context_length_used_p50 is None
    assert report.context_length_used_p95 is None


# ---------------------------------------------------------------------------
# Optional: cpu_fallback_rate
# ---------------------------------------------------------------------------


def test_cpu_fallback_rate_zero_when_none_occurred() -> None:
    records = [LocalLLMRecord(), LocalLLMRecord(), LocalLLMRecord()]
    report = build_local_llm_report(records)

    assert report.cpu_fallback_rate == 0.0


def test_cpu_fallback_rate_computed_from_occurred() -> None:
    records = [
        LocalLLMRecord(cpu_fallback_occurred=True),
        LocalLLMRecord(cpu_fallback_occurred=False),
        LocalLLMRecord(cpu_fallback_occurred=True),
        LocalLLMRecord(cpu_fallback_occurred=False),
    ]
    report = build_local_llm_report(records)

    assert report.cpu_fallback_rate == pytest.approx(0.5)


def test_cpu_fallback_rate_all_fallback() -> None:
    records = [LocalLLMRecord(cpu_fallback_occurred=True)] * 3
    report = build_local_llm_report(records)

    assert report.cpu_fallback_rate == 1.0


# ---------------------------------------------------------------------------
# Model metadata
# ---------------------------------------------------------------------------


def test_model_meta_none_by_default() -> None:
    report = build_local_llm_report([LocalLLMRecord()])

    assert report.model_meta is None


def test_model_meta_all_fields_included() -> None:
    meta = LocalLLMModelMeta(
        model_size_b=7.0,
        quantization="q4_0",
        context_length=4096,
        backend="llama.cpp",
    )
    report = build_local_llm_report([LocalLLMRecord()], model_meta=meta)

    assert report.model_meta is not None
    assert report.model_meta.model_size_b == 7.0
    assert report.model_meta.quantization == "q4_0"
    assert report.model_meta.context_length == 4096
    assert report.model_meta.backend == "llama.cpp"


def test_model_meta_partial_fields() -> None:
    meta = LocalLLMModelMeta(backend="mlx")
    report = build_local_llm_report([LocalLLMRecord()], model_meta=meta)

    assert report.model_meta is not None
    assert report.model_meta.backend == "mlx"
    assert report.model_meta.model_size_b is None
    assert report.model_meta.quantization is None
    assert report.model_meta.context_length is None


def test_model_meta_from_dict() -> None:
    meta: dict[str, object] = {"model_size_b": 13.0, "backend": "ollama"}
    report = build_local_llm_report([LocalLLMRecord()], model_meta=meta)

    assert report.model_meta is not None
    assert report.model_meta.model_size_b == 13.0
    assert report.model_meta.backend == "ollama"


def test_model_meta_extra_fields_ignored() -> None:
    meta: dict[str, object] = {"backend": "transformers", "unknown_field": "value"}
    report = build_local_llm_report([LocalLLMRecord()], model_meta=meta)

    assert report.model_meta is not None
    assert report.model_meta.backend == "transformers"


# ---------------------------------------------------------------------------
# Schema version and report shape
# ---------------------------------------------------------------------------


def test_schema_version_constant() -> None:
    assert LOCAL_LLM_REPORT_SCHEMA == "local-llm-metrics.v1"


def test_schema_version_in_report() -> None:
    report = build_local_llm_report([])

    assert report.schema_version == "local-llm-metrics.v1"


def test_report_excludes_raw_fields() -> None:
    report = build_local_llm_report([LocalLLMRecord(prompt_tokens_per_turn=100)])
    payload = json.loads(report.model_dump_json())

    assert "prompt" not in payload
    assert "raw" not in payload
    assert "records" not in payload
    assert "cpu_fallback_occurred" not in payload


def test_extra_record_fields_ignored() -> None:
    raw: dict[str, object] = {
        "prompt_tokens_per_turn": 50,
        "raw_prompt": "secret prompt text",
        "tool_output": "grep output here",
    }
    report = build_local_llm_report([raw])
    payload = json.loads(report.model_dump_json())

    assert report.total_prompt_tokens == 50
    assert "raw_prompt" not in payload
    assert "tool_output" not in payload


def test_all_optional_metrics_absent_gives_none_percentiles() -> None:
    records = [LocalLLMRecord(prompt_tokens_per_turn=100)] * 5
    report = build_local_llm_report(records)

    assert report.prefill_time_ms_p50 is None
    assert report.decode_tokens_per_second_p50 is None
    assert report.peak_vram_mb_p50 is None
    assert report.context_length_used_p50 is None


# ---------------------------------------------------------------------------
# Runner integration
# ---------------------------------------------------------------------------


def test_runner_run_local_llm_returns_report() -> None:
    records = [{"prompt_tokens_per_turn": 100, "context_pack_tokens": 50}]
    report = run_local_llm(records)

    assert isinstance(report, LocalLLMReport)
    assert report.total_records == 1
    assert report.total_prompt_tokens == 100


def test_runner_writes_aggregate_json(tmp_path: Path) -> None:
    output_path = tmp_path / "local_llm.json"
    records = [
        {"prompt_tokens_per_turn": 100, "context_pack_tokens": 50},
        {"prompt_tokens_per_turn": 200, "cpu_fallback_occurred": True},
    ]
    report = run_local_llm(records, output_path=output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload == report.model_dump(mode="json")
    assert "total_records" in payload
    assert "avg_prompt_tokens_per_turn" in payload
    assert "cpu_fallback_rate" in payload
    assert "records" not in payload
    assert "prompt" not in payload
    assert "cpu_fallback_occurred" not in payload


def test_runner_loads_list_fixture(tmp_path: Path) -> None:
    fixture = [
        {"prompt_tokens_per_turn": 100, "cpu_fallback_occurred": True},
        {"prompt_tokens_per_turn": 200, "cpu_fallback_occurred": False},
    ]
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")

    report = run_local_llm_fixture(fixture_path)

    assert report.total_records == 2
    assert report.total_prompt_tokens == 300
    assert report.cpu_fallback_rate == pytest.approx(0.5)


def test_runner_loads_object_fixture(tmp_path: Path) -> None:
    fixture = {
        "records": [
            {"prompt_tokens_per_turn": 80, "prefill_time_ms": 50.0},
            {"prompt_tokens_per_turn": 120, "prefill_time_ms": 150.0},
        ]
    }
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")

    report = run_local_llm_fixture(fixture_path)

    assert report.total_records == 2
    assert report.total_prompt_tokens == 200
    assert report.prefill_time_ms_p50 == 50.0
    assert report.prefill_time_ms_p95 == 150.0


def test_runner_passes_model_meta_to_fixture(tmp_path: Path) -> None:
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps([{"prompt_tokens_per_turn": 100}]), encoding="utf-8")
    meta = LocalLLMModelMeta(backend="mlx", quantization="q8_0")

    report = run_local_llm_fixture(fixture_path, model_meta=meta)

    assert report.model_meta is not None
    assert report.model_meta.backend == "mlx"
    assert report.model_meta.quantization == "q8_0"


def test_write_local_llm_report_creates_parent_dirs(tmp_path: Path) -> None:
    report = build_local_llm_report([LocalLLMRecord(prompt_tokens_per_turn=50)])
    output_path = tmp_path / "nested" / "dir" / "report.json"

    write_local_llm_report(report, output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "local-llm-metrics.v1"
    assert payload["total_records"] == 1
