#!/usr/bin/env python3
"""Build a small Action Memory PHOTON runtime checkpoint from JSON records."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    from photon_action_memory.models.checkpoint_builder import (
        build_action_memory_checkpoint_state,
        write_action_memory_checkpoint,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", type=Path, help="JSON list or object with a records list")
    parser.add_argument("--output", type=Path, required=True, help="Checkpoint output directory")
    parser.add_argument("--model-version", required=True, help="Runtime checkpoint model_version")
    parser.add_argument("--bias", type=float, default=0.5)
    parser.add_argument("--no-integrity", action="store_true")
    args = parser.parse_args(argv)

    records = _load_records(args.records)
    state = build_action_memory_checkpoint_state(records, bias=args.bias)
    paths = write_action_memory_checkpoint(
        args.output,
        model_version=args.model_version,
        state=state,
        write_integrity=not args.no_integrity,
    )
    print(
        json.dumps(
            {
                "checkpoint_dir": str(paths.checkpoint_dir),
                "manifest": str(paths.manifest_path),
                "state": str(paths.state_path),
                "weights": str(paths.weights_path),
                "integrity": str(paths.integrity_path) if paths.integrity_path else None,
                "model_version": paths.model_version,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _load_records(path: Path) -> list[Mapping[str, object]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    records: Any
    if isinstance(raw, dict):
        records = raw.get("records")
    else:
        records = raw
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise ValueError("records file must be a JSON list or an object with a records list")
    return records


if __name__ == "__main__":
    raise SystemExit(main())
