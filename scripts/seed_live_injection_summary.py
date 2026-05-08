#!/usr/bin/env python3
"""Seed the live-injection smoke ActionSummary into a running sidecar."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "shared" / "anvil_live_action_summary.json"


def _load_summary(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed the Anvil live-injection ActionSummary via /v1/summary/upsert.",
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:18765",
        help="Sidecar base URL. Default: %(default)s",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="ActionSummary fixture path. Default: %(default)s",
    )
    parser.add_argument(
        "--request-id",
        default="seed-anvil-live-codename-001",
        help="Upsert request_id. Default: %(default)s",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the upsert payload without sending it.",
    )
    args = parser.parse_args()

    summary = _load_summary(args.fixture)
    payload = {
        "schema_version": "action-memory.v0.2",
        "request_id": args.request_id,
        "summary": summary,
    }
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    try:
        result = _post_json(f"{args.url.rstrip('/')}/v1/summary/upsert", payload)
    except urllib.error.URLError as exc:
        print(f"failed to seed summary: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
