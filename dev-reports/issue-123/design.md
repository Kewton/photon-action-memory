# Issue #123 — Design

## Goal

Add the missing layer after Issue #121: a concrete Action Memory PHOTON runtime
checkpoint path that can be built, configured, smoke-tested, and compared
against deterministic scoring.

## Scope Decision

This is not a final-answer generation model. It is a small scorer checkpoint for
Action Memory candidates:

- summaries
- evidence
- next hints
- failed attempts

The implementation stays fail-open. Missing checkpoint, broken checkpoint, or
missing MLX must return deterministic scoring with a warning.

## Plan

1. Add a runtime checkpoint builder module that writes:
   - `manifest.json`
   - `state.json`
   - `weights.npz`
   - `integrity.json`
2. Add a tiny committed checkpoint fixture for CI.
3. Make strict scorer construction verify checkpoint integrity.
4. Add tests for:
   - builder state aggregation
   - fixture validity
   - `PHOTON_ACTION_MEMORY_CHECKPOINT` entering the PHOTON scorer path
   - strict integrity mismatch fallback
5. Document sidecar env setup and no-large-checkpoint policy.
6. Record a small deterministic-vs-PHOTON ranking comparison report.

## Non-goals

- Do not commit production-size checkpoint weights.
- Do not enable PHOTON scoring by default.
- Do not wire the scorer into `/v1/context/pack` in this issue.
- Do not add a session-aware state model.
