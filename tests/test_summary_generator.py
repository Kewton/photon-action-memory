"""Issue #121 — SummaryGeneratorProtocol contract & factory defaults."""

from __future__ import annotations

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionChunk,
)
from photon_action_memory.memory.summaries import ActionSummaryBuilder
from photon_action_memory.memory.summary_generator import (
    RuleBasedSummaryGenerator,
    SummaryGeneratorReport,
    make_summary_generator,
)


def _chunk() -> ActionChunk:
    return ActionChunk.model_validate(
        {
            "schema_version": DEFAULT_SCHEMA_VERSION_V2,
            "chunk_id": "chunk_001",
            "session_id": "sess_001",
            "kind": "repo_search",
            "summary": "Searched SessionStore",
            "outcome": "useful",
            "event_ids": ["evt_001"],
            "repo_id": "repo_001",
            "commit": "abc123",
        }
    )


class TestFactoryDefaults:
    def test_default_env_returns_rule_based(self) -> None:
        gen = make_summary_generator(env={})
        assert isinstance(gen, RuleBasedSummaryGenerator)

    def test_explicit_rule_based(self) -> None:
        gen = make_summary_generator(env={"PHOTON_SUMMARY_GENERATOR": "rule_based"})
        assert isinstance(gen, RuleBasedSummaryGenerator)

    def test_unknown_value_falls_back_to_rule_based(self) -> None:
        gen = make_summary_generator(env={"PHOTON_SUMMARY_GENERATOR": "magic"})
        assert isinstance(gen, RuleBasedSummaryGenerator)


class TestRuleBasedRegression:
    def test_rule_based_matches_builder_output(self) -> None:
        """The rule-based generator must produce a summary equivalent to the
        legacy ActionSummaryBuilder — the default Action Memory contract is
        unchanged in v0.4.0."""
        chunk = _chunk()
        gen = RuleBasedSummaryGenerator()
        summary, report = gen.build(chunk, summary_id="sum_xyz")
        baseline = ActionSummaryBuilder().build(chunk, summary_id="sum_xyz")
        assert summary.model_dump() == baseline.model_dump()
        assert report == SummaryGeneratorReport(generator_used="rule_based")

    def test_evidence_records_argument_is_accepted_and_ignored(self) -> None:
        chunk = _chunk()
        gen = RuleBasedSummaryGenerator()
        summary, _ = gen.build(
            chunk,
            evidence_records=[{"evidence_id": "evt_001", "content": "noop"}],
        )
        assert summary.summary_id


class TestLLMFactoryMissingMlx:
    def test_llm_mode_without_mlx_returns_always_fallback(self) -> None:
        """With no MLX installed, the factory must not raise — it returns a
        generator that always reports rule_based with the proper enum."""
        # The test environment does not have mlx_lm installed, so the LLM
        # generator construction raises MlxUnavailable; the factory must
        # transparently downgrade.
        gen = make_summary_generator(env={"PHOTON_SUMMARY_GENERATOR": "llm"})
        summary, report = gen.build(_chunk())
        assert report.generator_used == "rule_based"
        assert report.fallback_reason in {"mlx_unavailable", "model_unavailable"}
        assert summary.summary_id


class TestReportTelemetry:
    def test_report_default_no_fallback(self) -> None:
        report = SummaryGeneratorReport(generator_used="rule_based")
        assert report.fallback_reason is None
        assert report.notes == ()

    def test_report_with_fallback(self) -> None:
        report = SummaryGeneratorReport(
            generator_used="rule_based",
            fallback_reason="invalid_json",
        )
        assert report.fallback_reason == "invalid_json"
