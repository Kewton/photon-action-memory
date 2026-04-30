# Issue #3 Design Note

## Context

The sanitizer sits before the event store and dataset exporter, so callers need a small importable API that can sanitize text and path candidates without depending on exporter-specific state.

## Design

- Move the redaction regexes from the reference exporter into `photon_action_memory.memory.sanitizer`.
- Keep `sanitize_text(text: str | None) -> str` as the simple compatibility API.
- Add `sanitize_text_with_report(...)` for callers that need redaction counters.
- Normalize `/Users/...`, `/home/...`, and `/tmp/...` paths either relative to configured workspace roots or to `[ABS_PATH]/<basename>`.
- Add `filter_safe_path_candidates(...)` so candidate extractors/exporters can drop paths containing secrets or sensitive absolute prefixes.
- Keep false positives bounded by preserving hex digests and UUIDs when matching long secret-like tokens.

## Tests

Add focused pytest coverage for secret assignments, long tokens, email redaction, path normalization, ANSI/control character removal, report counters, and candidate filtering.
