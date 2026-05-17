# PHOTON Action Memory v0.4.0 Notes

v0.4.0 focuses on improving Action Memory quality without making local LLMs or
PHOTON checkpoints mandatory.

## Current Defaults

| Area | Default |
|---|---|
| Summary generation | `rule_based` |
| LLM draft generation | disabled unless `PHOTON_SUMMARY_GENERATOR=llm` |
| LLM fallback policy | `rule_based` |
| PHOTON checkpoint scorer | disabled unless a scorer is constructed with `PHOTON_ACTION_MEMORY_CHECKPOINT` |
| HTTP context-pack ranking | deterministic/feedback-adjusted |

## Implemented Pieces

- `SummaryGeneratorProtocol`
- `RuleBasedSummaryGenerator`
- opt-in `LLMDraftSummaryGenerator`
- summarize response telemetry: `generator_used` and `generator_fallback_reason`
- `ActionMemoryPhotonScorer` boundary
- PHOTON checkpoint manifest/state/integrity loader
- tiny PHOTON checkpoint fixture for CI
- `scripts/build_action_memory_checkpoint.py`

## Documents

| File | Purpose |
|---|---|
| `action-memory-llm-photon-improvement-plan.md` | Current v0.4.0 LLM draft summary and PHOTON checkpoint scorer plan/status. |
| `photon-checkpoint-scorer-eval.md` | Tiny checkpoint fixture, expected ranking difference, and verification commands. |

## Follow-up

A production PHOTON effect requires a trained or derived checkpoint from larger
eval/adoption logs and live wiring into `/v1/context/pack` ranking. Until that
lands, the HTTP sidecar keeps deterministic fallback behavior.
