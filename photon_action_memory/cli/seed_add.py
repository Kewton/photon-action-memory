"""Add or update an ActionSummary seed through the sidecar API."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

from photon_action_memory.api.schema_v2 import ActionSummary, UniversalMetadata


def build_seed_payload(
    summary: dict[str, Any],
    *,
    request_id: str,
    scope: str | None = None,
    metadata_json: str | None = None,
    repo_id: str | None = None,
    task_signature: str | None = None,
    summary_id: str | None = None,
) -> dict[str, Any]:
    """Return a validated /v1/summary/upsert payload."""
    updates: dict[str, Any] = {}
    if scope is not None:
        updates["applicability_scope"] = scope
    if metadata_json:
        metadata = UniversalMetadata.model_validate(json.loads(metadata_json))
        updates["universal_metadata"] = metadata.model_dump(exclude_none=True)
    if repo_id is not None:
        updates["repo_id"] = repo_id
    if task_signature is not None:
        updates["task_signature"] = task_signature
    if summary_id is not None:
        updates["summary_id"] = summary_id
    candidate = {**summary, **updates}
    validated = ActionSummary.model_validate(candidate)
    return {
        "schema_version": validated.schema_version,
        "request_id": request_id,
        "summary": validated.model_dump(mode="json", exclude_none=True),
    }


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        body = response.read().decode("utf-8")
    return cast(dict[str, Any], json.loads(body))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18765")
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--request-id", default="seed-cli-add")
    parser.add_argument("--scope", choices=("repo", "task_signature", "universal"))
    parser.add_argument("--metadata-json", help="UniversalMetadata JSON object")
    parser.add_argument("--repo-id")
    parser.add_argument("--task-signature")
    parser.add_argument("--summary-id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    summary = json.loads(args.fixture.read_text(encoding="utf-8"))
    payload = build_seed_payload(
        summary,
        request_id=args.request_id,
        scope=args.scope,
        metadata_json=args.metadata_json,
        repo_id=args.repo_id,
        task_signature=args.task_signature,
        summary_id=args.summary_id,
    )
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    try:
        result = _post_json(f"{args.url.rstrip('/')}/v1/summary/upsert", payload)
    except urllib.error.URLError as exc:
        print(f"failed to add seed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
