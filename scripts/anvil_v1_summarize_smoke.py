#!/usr/bin/env python3
"""End-to-end smoke for the Anvil /v1/summarize turn lifecycle.

Drives the post-v0.4.0-P1 turn lifecycle against a locally running
photon-action-memory sidecar at ``127.0.0.1:18765``:

    /v1/summarize -> /v1/summary/upsert
                  -> /v1/context/pack
                  -> /v1/evidence/expand (optional)
                  -> /v1/evaluate

The smoke is shaped for the v0.4.0 contract. If ``/v1/summarize`` cannot
produce a live summary yet (501 stub, or 200 with ``summary=null``), the
runner records a fixture fallback and continues from ``/v1/summary/upsert``
so the rest of the lifecycle is still verified.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SIDECAR_URL = "http://127.0.0.1:18765"
SCHEMA_VERSION = "action-memory.v0.2"

# Scenarios used by the "beta-gamma-light" Anvil eval slice.  Each scenario
# pins a stable repo_id, task_signature, and post-context-pack assertion
# that the runner uses to detect regressions or re-evaluate effects.
SCENARIOS: dict[str, dict[str, Any]] = {
    "S2-03": {
        "fixture": "anvil_eval_s2_03_action_summary.json",
        "kind": "regression",
        "repo": {"root": "/tmp/anvil-eval-s2-03", "name": "S2-03"},
        "task_signature": "sveltekit-route-edit-add-control",
        "user_request": "Add an interactive element to +page.svelte.",
        "must_survive_keywords": ["React", "Next"],
    },
    "S3-01": {
        "fixture": "anvil_eval_s3_01_action_summary.json",
        "kind": "effect",
        "repo": {"root": "/tmp/anvil-eval-s3-01", "name": "S3-01"},
        "task_signature": "python-bug-fix-calculator",
        "user_request": "Fix calculator.py add() so verify.py passes.",
        "must_surface_keywords": ["a + b", "verify.py"],
    },
    "S5-01": {
        "fixture": "anvil_eval_s5_01_action_summary.json",
        "kind": "effect",
        "repo": {"root": "/tmp/anvil-eval-s5-01", "name": "S5-01"},
        "task_signature": "python-bug-fix-anvil-md-verifier",
        "user_request": "Fix tool.py double() and run the ANVIL.md preferred verifier.",
        "must_surface_keywords": ["x + x", "custom_check.py"],
    },
}


@dataclass
class StepResult:
    """One step of the smoke run."""

    name: str
    status: str
    http_status: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.name,
            "status": self.status,
            "http_status": self.http_status,
            "detail": self.detail,
        }


def _post_json(
    url: str,
    payload: dict[str, Any],
    timeout: float = 5.0,
) -> tuple[int, dict[str, Any]]:
    """POST JSON; return ``(status, body)``. Body is ``{}`` on parse failure."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, _safe_json(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, _safe_json(body)


def _safe_json(body: str) -> dict[str, Any]:
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError:
        return {"raw": body}
    if isinstance(decoded, dict):
        return decoded
    return {"raw": decoded}


def _scenario_summary(scenario_id: str, fixtures_dir: Path) -> dict[str, Any]:
    scenario = SCENARIOS[scenario_id]
    fixture_path = fixtures_dir / scenario["fixture"]
    decoded = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError(f"fixture {fixture_path} did not decode to an object")
    return decoded


def _summarize_request(scenario_id: str, request_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "session_id": f"anvil-smoke-{scenario_id.lower()}-001",
        "chunk_ids": [f"anvil-eval-{scenario_id.lower().replace('-', '_')}-chunk-001"],
        "summary_level": "chunk",
        "policy": {
            "require_evidence_ids": True,
            "separate_fact_and_hypothesis": True,
            "include_failed_attempts": True,
            "include_avoid_guidance": True,
        },
    }


def _context_pack_request(scenario_id: str, summary_id: str, request_id: str) -> dict[str, Any]:
    scenario = SCENARIOS[scenario_id]
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "agent": {"name": "anvil", "version": "v0.4.0-smoke"},
        "repo": scenario["repo"],
        "task": {
            "user_request": scenario["user_request"],
            "mode": "act",
            "task_signature": scenario["task_signature"],
        },
        "working_memory": {
            "active_task": scenario["user_request"],
            "touched_files": [],
        },
        "candidate_summary_ids": [summary_id],
        "budget": {
            "max_memory_tokens": 1200,
            "max_evidence_chars": 4000,
        },
    }


def _evidence_expand_request(evidence_ids: list[str], request_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "evidence_ids": evidence_ids,
        "selected_evidence_ids": evidence_ids,
        "budget": {
            "max_chars_per_evidence": 1200,
            "max_total_chars": 4800,
        },
        "policy": {
            "redact_again": True,
            "allow_raw_full_output": False,
            "anvil_profile": True,
        },
    }


def _evaluate_request(
    scenario_id: str,
    request_id: str,
    context_pack_request_id: str,
    items_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "session_id": f"anvil-smoke-{scenario_id.lower()}-001",
        "agent": {"name": "anvil", "version": "v0.4.0-smoke"},
        "context_pack_event": {
            "context_pack_request_id": context_pack_request_id,
            "adoption_status": "adopted" if items_count > 0 else "shadow_not_injected",
            "evidence_expand_requested": False,
            "evidence_ids_expanded": [],
            "items_adopted_count": items_count,
            "items_ignored_count": 0,
            "outcome": "success",
            "latency_ms": 0.0,
        },
    }


def _items_text(context_pack: dict[str, Any]) -> str:
    items = context_pack.get("items") or []
    return "\n".join(str(item.get("text", "")) for item in items)


def run_smoke(
    scenario_id: str,
    *,
    sidecar_url: str = DEFAULT_SIDECAR_URL,
    poster: Any = None,
    fixtures_dir: Path | None = None,
) -> list[StepResult]:
    """Run the full turn lifecycle for one scenario.

    ``poster`` defaults to :func:`_post_json`; tests can inject a stub
    that doesn't require a running sidecar.
    """
    if scenario_id not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario_id}")
    post = poster or _post_json
    fixtures_path = fixtures_dir or (REPO_ROOT / "tests" / "fixtures" / "shared")
    base = sidecar_url.rstrip("/")
    request_id_prefix = uuid.uuid4().hex[:8]
    results: list[StepResult] = []

    # Step 1: /v1/summarize. May be a stub or may return 200 with no summary
    # when no matching events are available in the sidecar store.
    summarize_status, summarize_body = post(
        f"{base}/v1/summarize",
        _summarize_request(scenario_id, f"smoke-summarize-{request_id_prefix}"),
    )
    if summarize_status == 200 and isinstance(summarize_body.get("summary"), dict):
        summary = summarize_body["summary"]
        results.append(
            StepResult(
                name="summarize",
                status="ok",
                http_status=summarize_status,
                detail={"summary_id": summary.get("summary_id"), "source": "live"},
            )
        )
    elif summarize_status == 501 or (
        summarize_status == 200 and summarize_body.get("summary") is None
    ):
        # Fall back to the fixture so the rest of the turn lifecycle is still
        # verified end-to-end even when summarize cannot emit a summary.
        summary = _scenario_summary(scenario_id, fixtures_path)
        status = "summarize_stub" if summarize_status == 501 else "summary_fixture"
        note = (
            "P1 stub returned 501; using fixture summary."
            if summarize_status == 501
            else "summarize returned no summary; using fixture summary."
        )
        results.append(
            StepResult(
                name="summarize",
                status=status,
                http_status=summarize_status,
                detail={"note": note},
            )
        )
    else:
        results.append(
            StepResult(
                name="summarize",
                status="error",
                http_status=summarize_status,
                detail={"body": summarize_body},
            )
        )
        return results

    # Step 2: /v1/summary/upsert.  Stores the summary so /v1/context/pack
    # can resolve it by candidate_summary_ids.
    upsert_status, upsert_body = post(
        f"{base}/v1/summary/upsert",
        {
            "schema_version": SCHEMA_VERSION,
            "request_id": f"smoke-upsert-{request_id_prefix}",
            "summary": summary,
        },
    )
    results.append(
        StepResult(
            name="summary_upsert",
            status=upsert_body.get("status", "unknown") if upsert_status == 200 else "error",
            http_status=upsert_status,
            detail={"summary_id": upsert_body.get("summary_id")},
        )
    )
    if upsert_status != 200:
        return results

    # Step 3: /v1/context/pack with the upserted summary_id.
    pack_request_id = f"smoke-pack-{request_id_prefix}"
    pack_status, pack_body = post(
        f"{base}/v1/context/pack",
        _context_pack_request(scenario_id, summary["summary_id"], pack_request_id),
    )
    items = pack_body.get("context_pack", {}).get("items") or []
    assertion_status = _assert_scenario(scenario_id, pack_body) if pack_status == 200 else "skipped"
    results.append(
        StepResult(
            name="context_pack",
            status="ok" if pack_status == 200 else "error",
            http_status=pack_status,
            detail={
                "items_count": len(items),
                "sidecar_status": pack_body.get("sidecar_status"),
                "assertion": assertion_status,
            },
        )
    )
    if pack_status != 200:
        return results

    # Step 4: /v1/evidence/expand (optional, only if there are evidence_ids).
    evidence_ids: list[str] = []
    for item in items:
        evidence_ids.extend(item.get("evidence_ids") or [])
    if evidence_ids:
        expand_status, expand_body = post(
            f"{base}/v1/evidence/expand",
            _evidence_expand_request(evidence_ids[:3], f"smoke-expand-{request_id_prefix}"),
        )
        results.append(
            StepResult(
                name="evidence_expand",
                status="ok" if expand_status == 200 else "error",
                http_status=expand_status,
                detail={
                    "expanded_count": len(expand_body.get("expanded") or []),
                    "omitted_count": len(expand_body.get("omitted") or []),
                },
            )
        )
    else:
        results.append(
            StepResult(
                name="evidence_expand",
                status="skipped",
                http_status=None,
                detail={"reason": "no evidence_ids in context pack"},
            )
        )

    # Step 5: /v1/evaluate.  Always called, even in shadow mode.
    evaluate_status, evaluate_body = post(
        f"{base}/v1/evaluate",
        _evaluate_request(
            scenario_id,
            f"smoke-eval-{request_id_prefix}",
            pack_request_id,
            len(items),
        ),
    )
    results.append(
        StepResult(
            name="evaluate",
            status=evaluate_body.get("status", "unknown") if evaluate_status == 200 else "error",
            http_status=evaluate_status,
            detail={"logged": evaluate_body.get("logged")},
        )
    )
    return results


def _assert_scenario(scenario_id: str, pack_body: dict[str, Any]) -> str:
    """Return regression/effect verdict for the scenario.

    One of: ``regression-clear``, ``regression-detected``,
    ``effect-present``, ``effect-missing``.
    """
    scenario = SCENARIOS[scenario_id]
    text = _items_text(pack_body.get("context_pack", {}))
    if scenario["kind"] == "regression":
        keywords = scenario.get("must_survive_keywords") or []
        survived = all(kw in text for kw in keywords)
        return "regression-clear" if survived else "regression-detected"
    keywords = scenario.get("must_surface_keywords") or []
    surfaced = all(kw in text for kw in keywords)
    return "effect-present" if surfaced else "effect-missing"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Anvil /v1/summarize integration smoke.",
    )
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS),
        action="append",
        help="Scenario to run. Repeat to run multiple. Default: all.",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_SIDECAR_URL,
        help="Sidecar base URL (must point at 127.0.0.1:18765). Default: %(default)s",
    )
    args = parser.parse_args()

    if "3000" in args.url:
        print("error: port 3000 is not used for photon-action-memory", file=sys.stderr)
        return 2

    scenarios = args.scenario or sorted(SCENARIOS)
    report: dict[str, Any] = {}
    overall_status = 0
    for sid in scenarios:
        try:
            steps = run_smoke(sid, sidecar_url=args.url)
        except FileNotFoundError as exc:
            print(f"{sid}: fixture missing -> {exc}", file=sys.stderr)
            overall_status = 1
            continue
        report[sid] = [step.to_dict() for step in steps]
        # Any non-ok terminal step (including a context-pack regression) fails the run.
        for step in steps:
            if step.status == "error":
                overall_status = 1
            if step.name == "context_pack":
                assertion = step.detail.get("assertion")
                if assertion in {"regression-detected", "effect-missing"}:
                    overall_status = 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return overall_status


if __name__ == "__main__":
    raise SystemExit(main())
