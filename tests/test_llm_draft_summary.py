"""Issue #121 — LLM draft summary fallback paths and safety invariants."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionChunk,
)
from photon_action_memory.memory.llm_draft_summary import (
    LLMDraftConfig,
    LLMDraftSummaryGenerator,
    MlxUnavailable,
    ModelUnavailable,
    build_event_frame,
    build_user_prompt,
)
from photon_action_memory.memory.summary_generator import (
    SummaryGenerationAborted,
)


def _chunk(
    *,
    summary: str = "Searched SessionStore",
    outcome: str = "useful",
    event_ids: list[str] | None = None,
) -> ActionChunk:
    return ActionChunk.model_validate(
        {
            "schema_version": DEFAULT_SCHEMA_VERSION_V2,
            "chunk_id": "chunk_001",
            "session_id": "sess_001",
            "kind": "repo_search",
            "summary": summary,
            "outcome": outcome,
            "event_ids": ["evt_001", "evt_002"] if event_ids is None else event_ids,
            "repo_id": "repo_001",
            "commit": "abc123",
        }
    )


def _config(*, policy: str = "rule_based") -> LLMDraftConfig:
    return LLMDraftConfig(fallback_policy=policy)


def _make(
    callable_: Callable[[str, str, LLMDraftConfig], str],
    *,
    policy: str = "rule_based",
) -> LLMDraftSummaryGenerator:
    return LLMDraftSummaryGenerator(config=_config(policy=policy), generator_callable=callable_)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_valid_llm_output_used(self) -> None:
        def fake_call(system: str, user: str, cfg: LLMDraftConfig) -> str:
            return json.dumps(
                {
                    "facts": [
                        {
                            "text": "SessionStore writes to sqlite",
                            "evidence_ids": ["evt_001"],
                            "confidence": 0.8,
                        }
                    ],
                    "hypotheses": [],
                    "failed_attempts": [],
                    "next_hints": [],
                }
            )

        gen = _make(fake_call)
        summary, report = gen.build(_chunk())
        assert report.generator_used == "llm"
        assert report.fallback_reason is None
        assert summary.facts[0].text == "SessionStore writes to sqlite"
        assert summary.facts[0].evidence_ids == ["evt_001"]


# ---------------------------------------------------------------------------
# Fallback paths — each must produce a deterministic summary plus closed-enum reason
# ---------------------------------------------------------------------------


class TestFallbackReasons:
    def test_mlx_unavailable(self) -> None:
        def raise_mlx(system: str, user: str, cfg: LLMDraftConfig) -> str:
            raise MlxUnavailable("not installed")

        gen = _make(raise_mlx)
        _, report = gen.build(_chunk())
        assert report.generator_used == "rule_based"
        assert report.fallback_reason == "mlx_unavailable"

    def test_model_unavailable(self) -> None:
        def raise_model(system: str, user: str, cfg: LLMDraftConfig) -> str:
            raise ModelUnavailable("missing model")

        gen = _make(raise_model)
        _, report = gen.build(_chunk())
        assert report.fallback_reason == "model_unavailable"

    def test_empty_output(self) -> None:
        gen = _make(lambda s, u, c: "")
        _, report = gen.build(_chunk())
        assert report.fallback_reason == "empty_output"

    def test_whitespace_only_output_treated_as_empty(self) -> None:
        gen = _make(lambda s, u, c: "   \n   ")
        _, report = gen.build(_chunk())
        assert report.fallback_reason == "empty_output"

    def test_invalid_json(self) -> None:
        gen = _make(lambda s, u, c: "this is not json")
        _, report = gen.build(_chunk())
        assert report.fallback_reason == "invalid_json"

    def test_generation_exception(self) -> None:
        def raise_unknown(s: str, u: str, c: LLMDraftConfig) -> str:
            raise RuntimeError("oops")

        gen = _make(raise_unknown)
        _, report = gen.build(_chunk())
        assert report.fallback_reason == "generation_exception"

    def test_schema_validation_fails_when_evidence_id_unknown(self) -> None:
        """LLM cannot fabricate evidence_ids outside chunk.event_ids."""

        def fake(s: str, u: str, c: LLMDraftConfig) -> str:
            return json.dumps(
                {
                    "facts": [
                        {
                            "text": "fabricated claim",
                            "evidence_ids": ["evt_made_up"],
                            "confidence": 0.9,
                        }
                    ]
                }
            )

        gen = _make(fake)
        _, report = gen.build(_chunk())
        assert report.fallback_reason == "schema_validation_failed"

    def test_quality_gate_rejects_answer_leak(self) -> None:
        def fake(s: str, u: str, c: LLMDraftConfig) -> str:
            return json.dumps(
                {
                    "facts": [
                        {
                            "text": (
                                "summarize.py prints a JSON object with keys alpha, beta, and total"
                            ),
                            "evidence_ids": ["evt_001"],
                            "confidence": 0.9,
                        }
                    ]
                }
            )

        gen = _make(fake)
        _, report = gen.build(_chunk())
        assert report.fallback_reason == "quality_gate_rejected"


class TestAbortPolicy:
    def test_abort_policy_raises_instead_of_falling_back(self) -> None:
        gen = _make(lambda s, u, c: "", policy="abort")
        with pytest.raises(SummaryGenerationAborted):
            gen.build(_chunk())


# ---------------------------------------------------------------------------
# Allowlist DTO — no raw output, no secrets, no home paths
# ---------------------------------------------------------------------------


class TestSummaryDraftEventFrame:
    def test_frame_drops_secret_from_chunk_summary(self) -> None:
        chunk = _chunk(summary="api_key=sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890 found")
        frame = build_event_frame(chunk, evidence_records=None)
        prompt = build_user_prompt(frame)
        assert "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890" not in prompt

    def test_frame_drops_home_path_from_chunk_summary(self) -> None:
        chunk = _chunk(summary="error at /Users/maenokota/secret/notes.md")
        frame = build_event_frame(chunk, evidence_records=None)
        prompt = build_user_prompt(frame)
        assert "/Users/maenokota" not in prompt

    def test_frame_omits_evidence_excerpt_when_sensitive(self) -> None:
        chunk = _chunk()
        records = [
            {
                "evidence_id": "evt_001",
                "content": "api_key=sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890",
            }
        ]
        frame = build_event_frame(chunk, evidence_records=records)
        # After sanitization the secret is redacted; the excerpt may keep the
        # redacted placeholder but never the secret itself.
        for excerpt in frame.event_excerpts:
            assert "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890" not in excerpt.excerpt

    def test_frame_includes_clean_evidence_excerpt(self) -> None:
        chunk = _chunk()
        records = [{"evidence_id": "evt_001", "content": "imports the SessionStore module"}]
        frame = build_event_frame(chunk, evidence_records=records)
        assert frame.event_excerpts
        assert frame.event_excerpts[0].event_id == "evt_001"

    def test_prompt_contains_only_allowlisted_keys(self) -> None:
        chunk = _chunk()
        frame = build_event_frame(chunk, evidence_records=None)
        prompt = build_user_prompt(frame)
        decoded = json.loads(prompt)
        assert set(decoded.keys()) == {
            "chunk_id",
            "kind",
            "outcome",
            "summary",
            "evidence_ids",
            "events",
            "schema",
        }


# ---------------------------------------------------------------------------
# Import safety — no MLX import at module load
# ---------------------------------------------------------------------------


class TestImportSafety:
    def test_module_import_does_not_import_mlx(self) -> None:
        """Importing the LLM draft summary module in a fresh interpreter must
        not trigger an mlx/mlx_lm import. We run a subprocess so the check is
        not polluted by other tests that may have already loaded mlx."""
        import subprocess
        import sys

        leaked = "sorted(k for k in sys.modules if k.startswith('mlx'))"
        script = (
            "import sys; "
            "import photon_action_memory.memory.llm_draft_summary as m; "
            f"assert 'mlx' not in sys.modules, {leaked}; "
            "assert 'mlx_lm' not in sys.modules; "
            "print('ok')"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "ok" in result.stdout
