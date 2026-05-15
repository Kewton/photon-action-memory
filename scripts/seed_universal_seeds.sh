#!/usr/bin/env bash
# Seed universal photon memories.
# These fixtures use applicability_scope="universal" and metadata filters.
# Run from the photon-action-memory repo root.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FIXTURES="$SCRIPT_DIR/../tests/fixtures/shared"

SEEDS=(
  "universal_pytest_verbose_action_summary.json:seed-universal-pytest-verbose"
  "universal_python_pathlib_action_summary.json:seed-universal-python-pathlib"
  "universal_fastapi_pydantic_action_summary.json:seed-universal-fastapi-pydantic"
  "universal_rust_result_action_summary.json:seed-universal-rust-result"
  "universal_rust_clippy_action_summary.json:seed-universal-rust-clippy"
  "universal_node_package_scripts_action_summary.json:seed-universal-node-package-scripts"
  "universal_sveltekit_native_action_summary.json:seed-universal-sveltekit-native"
  "universal_git_amend_published_action_summary.json:seed-universal-git-amend-published"
  "universal_git_worktree_action_summary.json:seed-universal-git-worktree"
  "universal_macos_mlx_action_summary.json:seed-universal-macos-mlx"
)

echo "=== Seeding universal photon memories ==="
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
