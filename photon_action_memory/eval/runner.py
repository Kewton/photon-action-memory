"""Offline evaluation runner for normalized shadow fixtures."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from photon_action_memory.eval.metrics import MetricsReport, RawRecord, build_metrics_report


def run_eval(
    records: Iterable[RawRecord],
    *,
    top_k: int = 3,
    output_path: str | Path | None = None,
) -> MetricsReport:
    """Run eval over normalized records and optionally write aggregate JSON."""
    report = build_metrics_report(list(records), top_k=top_k)
    if output_path is not None:
        write_metrics_report(report, output_path)
    return report


def run_fixture(
    fixture_path: str | Path,
    *,
    top_k: int = 3,
    output_path: str | Path | None = None,
) -> MetricsReport:
    """Load a JSON fixture and run aggregate eval metrics."""
    return run_eval(load_fixture(fixture_path), top_k=top_k, output_path=output_path)


def load_fixture(fixture_path: str | Path) -> list[Mapping[str, Any]]:
    """Load normalized eval records from a JSON list or `{records: [...]}` object."""
    path = Path(fixture_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict) and isinstance(payload.get("records"), list):
        records = payload["records"]
    else:
        raise ValueError("eval fixture must be a JSON list or an object with a records list")

    if not all(isinstance(record, dict) for record in records):
        raise ValueError("eval fixture records must be JSON objects")

    return records


def write_metrics_report(report: MetricsReport, output_path: str | Path) -> None:
    """Write the aggregate report without raw fixture records."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")


__all__ = [
    "load_fixture",
    "run_eval",
    "run_fixture",
    "write_metrics_report",
]
