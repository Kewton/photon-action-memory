#!/usr/bin/env bash
# Seed common cross-repo photon memories.
# These fixtures use repo_id="__common__" and task_signature-specific retrieval.
# Run from the photon-action-memory repo root.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FIXTURES="$SCRIPT_DIR/../tests/fixtures/shared"

SEEDS=(
  "common_pytest_action_summary.json:seed-common-pytest-verbose"
  "common_rust_error_handling_action_summary.json:seed-common-rust-result-handling"
  "common_sveltekit_vs_react_action_summary.json:seed-common-sveltekit-vs-react"
)

echo "=== Seeding common photon memories ==="
for entry in "${SEEDS[@]}"; do
  fixture="${entry%%:*}"
  request_id="${entry##*:}"
  echo -n "  $fixture ... "
  python3 "$SCRIPT_DIR/seed_live_injection_summary.py" \
    --fixture "$FIXTURES/$fixture" \
    --request-id "$request_id" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['status'])"
done
echo "=== Done ==="
