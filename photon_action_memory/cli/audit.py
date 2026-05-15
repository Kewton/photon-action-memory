"""Run governance audits against the sidecar (contradiction detection)."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, cast


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read().decode("utf-8")
    return cast(dict[str, Any], json.loads(body))


def build_contradiction_payload(
    *,
    request_id: str,
    repo_id: str | None,
    task_signature: str | None,
    limit: int,
    schema_version: str = "action-memory.v0.2",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "request_id": request_id,
        "limit": limit,
    }
    if repo_id is not None:
        payload["repo_id"] = repo_id
    if task_signature is not None:
        payload["task_signature"] = task_signature
    return payload


def _detect_contradictions(args: argparse.Namespace) -> int:
    payload = build_contradiction_payload(
        request_id=args.request_id,
        repo_id=args.repo_id,
        task_signature=args.task_signature,
        limit=args.limit,
    )
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    try:
        result = _post_json(
            f"{args.url.rstrip('/')}/v1/seeds/audit/contradictions",
            payload,
        )
    except urllib.error.URLError as exc:
        print(f"failed to run audit: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    pairs = result.get("pairs") or []
    return 1 if pairs else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18765")
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect = subparsers.add_parser(
        "detect-contradictions",
        help="run contradiction detection on stored seeds",
    )
    detect.add_argument("--request-id", default="audit-contradictions")
    detect.add_argument("--repo-id")
    detect.add_argument("--task-signature")
    detect.add_argument("--limit", type=int, default=200)
    detect.add_argument("--dry-run", action="store_true")
    detect.set_defaults(func=_detect_contradictions)

    args = parser.parse_args(argv)
    return cast(int, args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
