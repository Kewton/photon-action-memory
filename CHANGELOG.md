# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Live `/v1/summarize` documentation for rule-based summary generation,
  optional LLM draft generation, and generator fallback telemetry.
- PHOTON checkpoint scorer documentation for local checkpoint construction,
  strict integrity verification, tiny CI fixture usage, and deterministic
  fallback behavior.
- Updated Anvil operations guidance for the current summarize/upsert/context
  pack/evaluate lifecycle.

### Changed

- README and operations docs now describe the current sidecar implementation
  instead of the v0.1.0 bootstrap state.
- Active documentation now distinguishes the optional PHOTON scorer boundary
  from the still-deterministic default HTTP context-pack ranking path.

## [0.1.0] - 2026-04-30

### Added

- Initial PHOTON Action Memory package.
- Local-first sidecar schema, event ingestion, suggestion API, and fallback ranking.
- Optional PHOTON / MLX adapter surface.
- Sanitizer, local event store, dataset exporter, evaluation metrics, and Anvil fixtures.

[unreleased]: https://github.com/Kewton/photon-action-memory/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Kewton/photon-action-memory/releases/tag/v0.1.0
