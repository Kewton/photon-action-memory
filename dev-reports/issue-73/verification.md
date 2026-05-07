# Verification - Issue #73

## Commands Run

```bash
python -m pytest tests/test_sidecar_api.py tests/test_shared_fixtures.py tests/test_rollout_policy.py -q
```

Result:

```text
30 passed in 0.28s
```

```bash
ruff format --check .
```

Result:

```text
88 files already formatted
```

```bash
ruff check .
```

Result:

```text
All checks passed!
```

## Documentation Checks

Confirmed the docs include:

- `127.0.0.1:18765` sidecar URL.
- No recommendation to use port 3000.
- Anvil env/defaults from the issue body.
- Shadow/canary/rollback checklists.
- Shared fixture update procedure.
- Anvil vs photon troubleshooting ownership.

