"""Dataset JSONL utilities."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ExportStats:
    """Counters collected while exporting trajectory examples."""

    counters: Counter[str] = field(default_factory=Counter)
    actions: Counter[str] = field(default_factory=Counter)
    tools: Counter[str] = field(default_factory=Counter)
    redactions: Counter[str] = field(default_factory=Counter)
    examples_by_cli: Counter[str] = field(default_factory=Counter)
    context_chars: list[int] = field(default_factory=list)
    target_file_counts: list[int] = field(default_factory=list)

    def inc(self, key: str, amount: int = 1) -> None:
        self.counters[key] += amount

    def record_redactions(self, counts: Mapping[str, int]) -> None:
        self.redactions.update(counts)


def stable_hash(text: str, length: int = 16) -> str:
    """Return a stable short hash suitable for source metadata."""
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:length]


def write_jsonl(path: str | Path, examples: Iterable[Mapping[str, Any]]) -> int:
    """Write examples as canonical JSONL and return the row count."""
    jsonl_path = Path(path)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for example in examples:
            handle.write(json.dumps(example, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            count += 1
    return count


def write_redaction_report(path: str | Path, redactions: Mapping[str, int]) -> None:
    """Write redaction counters as JSON."""
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(dict(redactions), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def summarize_export_stats(
    stats: ExportStats, *, output: str | Path | None = None
) -> dict[str, Any]:
    """Build a JSON-serializable export summary."""

    def avg(values: list[int]) -> float:
        return round(sum(values) / len(values), 1) if values else 0.0

    return {
        "output": str(output) if output is not None else None,
        "counters": dict(stats.counters),
        "examples_by_action": dict(stats.actions),
        "examples_by_tool": dict(stats.tools),
        "examples_by_cli": dict(stats.examples_by_cli),
        "redactions": dict(stats.redactions),
        "avg_context_chars": avg(stats.context_chars),
        "avg_target_files": avg(stats.target_file_counts),
    }


__all__ = [
    "ExportStats",
    "stable_hash",
    "summarize_export_stats",
    "write_jsonl",
    "write_redaction_report",
]
