"""Tests for the Anvil /v1/summarize integration smoke runner (Issue #88).

The runner drives the post-v0.4.0-P1 turn lifecycle. These tests verify both
the fixture fallback path and the live (200 with summary) path against a
FastAPI ``TestClient`` rather than a live sidecar.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from photon_action_memory.api.server import create_app
from photon_action_memory.memory.store import SQLiteEventStore
from photon_action_memory.memory.summary_store import SummaryStore

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
FIXTURES_SHARED = Path(__file__).parent / "fixtures" / "shared"

# scripts/ is not a package; add it to sys.path so we can import the runner.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import anvil_v1_summarize_smoke as smoke  # type: ignore[import-not-found] # noqa: E402


@pytest.fixture()
def _stub_fixture_dir(tmp_path: Path) -> Path:
    """Create the three S-scenario summary fixtures used by the runner.

    The real fixtures live on ``develop`` (commits ``fc80f54`` / ``d280e35``)
    and are referenced by the runner via stable filenames. The tests pin the
    runner against a tmp directory so they pass on any branch.
    """
    fixtures = {
        "anvil_eval_s2_03_action_summary.json": {
            "schema_version": "action-memory.v0.2",
            "summary_id": "anvil-eval-s2-03-svelte-001",
            "repo_id": "S2-03",
            "task_signature": "sveltekit-route-edit-add-control",
            "summary_level": "chunk",
            "facts": [
                {
                    "text": (
                        "Repo S2-03 is a SvelteKit project. "
                        "verify.mjs fails if React or Next is detected."
                    ),
                    "evidence_ids": ["anvil-eval-s2-03-ev-001"],
                    "confidence": 0.97,
                }
            ],
            "avoid": [
                {
                    "action": "add React or Next.js components",
                    "reason": "verify.mjs explicitly fails if React or Next is detected",
                    "evidence_ids": ["anvil-eval-s2-03-ev-001"],
                }
            ],
            "validity": {"status": "valid"},
        },
        "anvil_eval_s3_01_action_summary.json": {
            "schema_version": "action-memory.v0.2",
            "summary_id": "anvil-eval-s3-01-calculator-001",
            "repo_id": "S3-01",
            "task_signature": "python-bug-fix-calculator",
            "summary_level": "chunk",
            "facts": [
                {
                    "text": (
                        "calculator.py add() returns a - b. Fix: change to a + b. "
                        "Verify with python3 verify.py."
                    ),
                    "evidence_ids": ["anvil-eval-s3-01-ev-001"],
                    "confidence": 0.99,
                }
            ],
            "validity": {"status": "valid"},
        },
        "anvil_eval_s5_01_action_summary.json": {
            "schema_version": "action-memory.v0.2",
            "summary_id": "anvil-eval-s5-01-tool-double-001",
            "repo_id": "S5-01",
            "task_signature": "python-bug-fix-anvil-md-verifier",
            "summary_level": "chunk",
            "facts": [
                {
                    "text": (
                        "tool.py double(x) returns x + x + 1. Fix: return x + x. "
                        "Use python3 custom_check.py per ANVIL.md."
                    ),
                    "evidence_ids": ["anvil-eval-s5-01-ev-001"],
                    "confidence": 0.99,
                }
            ],
            "validity": {"status": "valid"},
        },
    }
    for name, body in fixtures.items():
        (tmp_path / name).write_text(json.dumps(body), encoding="utf-8")
    return tmp_path


def _client_poster(client: TestClient) -> Any:
    def post(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        path = url.split("127.0.0.1:18765", 1)[-1] if "127.0.0.1:18765" in url else url
        response = client.post(path, json=payload)
        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text}
        if not isinstance(body, dict):
            body = {"raw": body}
        return response.status_code, body

    return post


def test_smoke_runner_uses_fixture_when_summarize_returns_no_summary(
    tmp_path: Path,
    _stub_fixture_dir: Path,
) -> None:
    event_store = SQLiteEventStore(tmp_path / "events.sqlite")
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    app = create_app(event_store, summary_store)

    with TestClient(app) as client:
        steps = smoke.run_smoke(
            "S3-01",
            sidecar_url=smoke.DEFAULT_SIDECAR_URL,
            poster=_client_poster(client),
            fixtures_dir=_stub_fixture_dir,
        )

    by_name = {s.name: s for s in steps}
    assert by_name["summarize"].http_status == 200
    assert by_name["summarize"].status == "summary_fixture"
    assert by_name["summary_upsert"].status == "stored"
    assert by_name["context_pack"].status == "ok"
    assert by_name["context_pack"].detail["assertion"] in {"effect-present", "effect-missing"}
    assert by_name["evaluate"].status == "ok"
    assert by_name["evaluate"].detail["logged"] == 1


def test_smoke_runner_consumes_live_summarize_response(
    tmp_path: Path,
    _stub_fixture_dir: Path,
) -> None:
    """When /v1/summarize returns 200, the smoke uses the response summary."""
    event_store = SQLiteEventStore(tmp_path / "events.sqlite")
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    app = create_app(event_store, summary_store)
    live_summary = json.loads(
        (_stub_fixture_dir / "anvil_eval_s5_01_action_summary.json").read_text(encoding="utf-8")
    )

    real_poster = _client_poster(TestClient(app))

    def poster(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if url.endswith("/v1/summarize"):
            stubbed: dict[str, Any] = {
                "schema_version": "action-memory.v0.2",
                "request_id": payload["request_id"],
                "summary": live_summary,
                "validation": {"status": "valid", "score": 0.95},
            }
            return 200, stubbed
        status, body = real_poster(url, payload)
        return status, body

    with TestClient(app):
        steps = smoke.run_smoke(
            "S5-01",
            sidecar_url=smoke.DEFAULT_SIDECAR_URL,
            poster=poster,
            fixtures_dir=_stub_fixture_dir,
        )

    by_name = {s.name: s for s in steps}
    assert by_name["summarize"].http_status == 200
    assert by_name["summarize"].status == "ok"
    assert by_name["summarize"].detail["source"] == "live"
    assert by_name["summary_upsert"].status == "stored"


def test_smoke_runner_detects_s2_03_regression(tmp_path: Path, _stub_fixture_dir: Path) -> None:
    """S2-03 must keep the React/Next avoid guidance prompt-visible.

    Mutate the fixture so the avoid text is stripped — the smoke must flag
    the change as ``regression-detected``.
    """
    bad = json.loads(
        (_stub_fixture_dir / "anvil_eval_s2_03_action_summary.json").read_text(encoding="utf-8")
    )
    bad["facts"][0]["text"] = "Repo S2-03 is a project."
    bad["avoid"] = []
    (_stub_fixture_dir / "anvil_eval_s2_03_action_summary.json").write_text(
        json.dumps(bad), encoding="utf-8"
    )

    event_store = SQLiteEventStore(tmp_path / "events.sqlite")
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    app = create_app(event_store, summary_store)

    with TestClient(app) as client:
        steps = smoke.run_smoke(
            "S2-03",
            sidecar_url=smoke.DEFAULT_SIDECAR_URL,
            poster=_client_poster(client),
            fixtures_dir=_stub_fixture_dir,
        )

    by_name = {s.name: s for s in steps}
    assert by_name["context_pack"].detail["assertion"] == "regression-detected"


def test_smoke_runner_rejects_port_3000(
    tmp_path: Path,
    _stub_fixture_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """main() must refuse a URL containing port 3000."""
    import argparse

    sys_argv_backup = sys.argv
    sys.argv = ["smoke", "--url", "http://127.0.0.1:3000"]
    try:
        rc = smoke.main()
    finally:
        sys.argv = sys_argv_backup

    captured = capsys.readouterr()
    assert rc == 2
    assert "3000" in captured.err
    # silence unused-arg lint
    _ = (tmp_path, _stub_fixture_dir, argparse)
