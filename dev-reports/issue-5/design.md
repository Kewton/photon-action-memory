# Issue #5 Design Note

## Scope

Implement the smallest M2 sidecar MVP that can run without a PHOTON model,
checkpoint, or the later full schema/store milestones:

- FastAPI `GET /health`
- `POST /v1/events` backed by a local SQLite append-only event store
- `POST /v1/suggest` with deterministic no-model suggestions
- `POST /v1/summarize` and `POST /v1/evaluate` fixed as `501` stubs
- Python client methods that fail open on sidecar errors or timeouts

## Approach

The API schema is intentionally permissive: required top-level fields are
validated where M2 needs a stable contract, while nested agent/repo/task/event
payloads remain dictionaries so M1 can still harden them later without this PR
overfitting early. Unknown optional fields are accepted by Pydantic models.

The event store uses Python's standard `sqlite3` module and stores one JSON
payload per event. The default database path is under the system temp directory
so the sidecar works out of the box during local smoke tests. Tests can inject a
temporary store through `create_app`.

Suggestion generation is a deterministic fallback. It extracts touched files and
recent event summaries from the request, returns read/search suggestions up to
the requested budget, and emits a warning that model scoring is unavailable.
This satisfies fail-open behavior while leaving a narrow seam for future ranking
and model-backed scoring.

The client uses `httpx.Client` with a timeout and catches `httpx.HTTPError`.
For suggest failures it returns the same response shape as the server, with an
empty suggestions list and a `sidecar_unavailable` warning.
