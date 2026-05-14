"""Multilingual seed fixture tests for Anvil expanded eval scenarios (Issue #98).

Each ``tests/fixtures/shared/anvil_eval_*_action_summary.json`` seed must carry
both English and Japanese variants for ``facts`` / ``next_hints`` (and
``avoid`` where applicable), tagged with a ``lang`` field. The bilingual pair
keeps Anvil's Japanese task descriptions aligned with retrieved facts while
preserving English coverage, and must still fit the 800-token context-pack
budget.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionSummary,
    ContextPackBudget,
)
from photon_action_memory.api.server import create_app
from photon_action_memory.context.pack import build_context_pack
from photon_action_memory.context.render import render_summary
from photon_action_memory.memory.store import SQLiteEventStore
from photon_action_memory.memory.summary_store import SummaryStore

REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED = REPO_ROOT / "tests" / "fixtures" / "shared"
SEED_SCRIPT = REPO_ROOT / "scripts" / "seed_expanded_eval_scenarios.sh"

SEED_FILES: tuple[str, ...] = (
    "anvil_eval_s1_02_action_summary.json",
    "anvil_eval_s2_03_action_summary.json",
    "anvil_eval_s2_03_en_action_summary.json",
    "anvil_eval_s3_01_action_summary.json",
    "anvil_eval_s3_01_en_action_summary.json",
    "anvil_eval_s3_03_action_summary.json",
    "anvil_eval_s3_04_action_summary.json",
    "anvil_eval_s5_01_action_summary.json",
    "anvil_eval_s5_01_en_action_summary.json",
    "anvil_eval_s6_04_action_summary.json",
    "anvil_eval_sp01_action_summary.json",
)

CROSS_LINGUAL_EN_SEEDS: dict[str, str] = {
    "anvil_eval_s2_03_en_action_summary.json": "S2-03-en",
    "anvil_eval_s3_01_en_action_summary.json": "S3-01-en",
    "anvil_eval_s5_01_en_action_summary.json": "S5-01-en",
}

_JA_CHAR_RE = re.compile(r"[぀-ヿ㐀-鿿]")


def _load(filename: str) -> dict[str, object]:
    raw = json.loads((SHARED / filename).read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def _langs(entries: list[dict[str, object]]) -> set[str]:
    return {str(entry.get("lang")) for entry in entries if entry.get("lang")}


@pytest.mark.parametrize("filename", SEED_FILES)
def test_seed_validates_as_action_summary(filename: str) -> None:
    raw = _load(filename)
    summary = ActionSummary.model_validate(raw)
    assert summary.schema_version == DEFAULT_SCHEMA_VERSION_V2
    assert summary.facts, f"{filename} must carry at least one fact"
    assert summary.next_hints, f"{filename} must carry at least one next_hint"


@pytest.mark.parametrize("filename", SEED_FILES)
def test_seed_has_en_and_ja_variants(filename: str) -> None:
    raw = _load(filename)
    fact_langs = _langs(raw["facts"])  # type: ignore[arg-type]
    hint_langs = _langs(raw["next_hints"])  # type: ignore[arg-type]
    assert fact_langs == {"en", "ja"}, f"{filename} facts must include en and ja, got {fact_langs}"
    assert hint_langs == {"en", "ja"}, (
        f"{filename} next_hints must include en and ja, got {hint_langs}"
    )
    avoid_entries = raw.get("avoid") or []
    if avoid_entries:
        assert _langs(avoid_entries) == {"en", "ja"}, (  # type: ignore[arg-type]
            f"{filename} avoid must include en and ja when present"
        )


@pytest.mark.parametrize("filename", SEED_FILES)
def test_seed_rendered_text_contains_japanese(filename: str) -> None:
    summary = ActionSummary.model_validate(_load(filename))
    text = render_summary(summary)
    assert _JA_CHAR_RE.search(text), f"{filename} rendered text must contain Japanese characters"
    fact_lines = [line for line in text.splitlines() if line.startswith("FACT:")]
    assert len(fact_lines) >= 2, f"{filename} rendered text must surface both EN and JA fact lines"
    hint_lines = [line for line in text.splitlines() if line.startswith("HINT:")]
    assert len(hint_lines) >= 2, f"{filename} rendered text must surface both EN and JA hint lines"


@pytest.mark.parametrize("filename", SEED_FILES)
def test_seed_fits_default_context_pack_budget(filename: str) -> None:
    summary = ActionSummary.model_validate(_load(filename))
    pack, decisions = build_context_pack(
        request_id=f"test-{filename}",
        session_id=summary.session_id,
        repo_id=summary.repo_id,
        summaries=[summary],
        budget=ContextPackBudget(),
    )
    assert pack.token_budget.max_tokens == 800
    assert pack.token_budget.estimated_tokens <= 800
    assert len(pack.items) == 1, (
        f"{filename} must be admitted (decisions={[d.decision for d in decisions]})"
    )
    assert pack.items[0].id == summary.summary_id


def test_all_seeds_fit_combined_default_budget() -> None:
    summaries = [ActionSummary.model_validate(_load(name)) for name in SEED_FILES]
    pack, _ = build_context_pack(
        request_id="test-combined",
        session_id=None,
        repo_id=None,
        summaries=summaries,
        budget=ContextPackBudget(),
    )
    assert pack.token_budget.max_tokens == 800
    assert pack.token_budget.estimated_tokens <= 800


def test_seed_script_references_all_fixtures() -> None:
    assert SEED_SCRIPT.exists(), "seed_expanded_eval_scenarios.sh must exist"
    contents = SEED_SCRIPT.read_text(encoding="utf-8")
    for filename in SEED_FILES:
        assert filename in contents, f"seed script must reference {filename}"


@pytest.mark.parametrize(("filename", "repo_id"), CROSS_LINGUAL_EN_SEEDS.items())
def test_en_variant_seed_repo_id_matches_anvil_workdir(filename: str, repo_id: str) -> None:
    summary = ActionSummary.model_validate(_load(filename))
    assert summary.repo_id == repo_id
    assert repo_id.lower().replace("-", "_") in filename


@pytest.mark.parametrize(("filename", "repo_id"), CROSS_LINGUAL_EN_SEEDS.items())
def test_en_variant_seed_resolves_by_exact_repo_id(
    tmp_path: Path, filename: str, repo_id: str
) -> None:
    summary_store = SummaryStore(tmp_path / "summaries.sqlite")
    event_store = SQLiteEventStore(tmp_path / "events.sqlite")
    summary = ActionSummary.model_validate(_load(filename))
    summary_store.upsert(summary)

    body = {
        "schema_version": DEFAULT_SCHEMA_VERSION_V2,
        "request_id": f"pack-{repo_id}",
        "agent": {"name": "anvil", "version": "dev"},
        "repo": {"root": f"/tmp/anvil-eval/{repo_id}", "name": repo_id},
        "task": {
            "user_request": "Use photon memory for the English cross-lingual scenario.",
            "mode": "act",
            "summary": "cross_lingual EN scenario",
        },
        "working_memory": {"touched_files": []},
        "recent_event_ids": [],
        "candidate_summary_ids": [],
        "budget": {"max_memory_tokens": 800, "max_evidence_chars": 1200},
    }
    with TestClient(create_app(event_store, summary_store)) as client:
        response = client.post("/v1/context/pack", json=body)

    assert response.status_code == 200
    payload = response.json()
    assert payload["sidecar_status"] == "ok"
    assert payload["context_pack"]["repo_id"] == repo_id
    assert [item["id"] for item in payload["context_pack"]["items"]] == [summary.summary_id]
    assert payload["admission_decisions"][0]["decision"] == "admit"
