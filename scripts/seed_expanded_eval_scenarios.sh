#!/usr/bin/env bash
# Seed photon memories for Anvil expanded eval scenarios with multilingual variants.
# Each fixture carries lang=en/ja paired facts/next_hints/avoid for Anvil task alignment.
# The *-en fixtures cover Anvil cross_lingual workdir repo_id values (Issue #101).
# Run from the photon-action-memory repo root.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FIXTURES="$SCRIPT_DIR/../tests/fixtures/shared"

SEEDS=(
  "anvil_eval_s1_02_action_summary.json:seed-anvil-eval-s1-02-001"
  "anvil_eval_s2_03_action_summary.json:seed-anvil-eval-s2-03-001"
  "anvil_eval_s2_03_en_action_summary.json:seed-anvil-eval-s2-03-en-001"
  "anvil_eval_s3_01_action_summary.json:seed-anvil-eval-s3-01-001"
  "anvil_eval_s3_01_en_action_summary.json:seed-anvil-eval-s3-01-en-001"
  "anvil_eval_s3_03_action_summary.json:seed-anvil-eval-s3-03-001"
  "anvil_eval_s3_04_action_summary.json:seed-anvil-eval-s3-04-001"
  "anvil_eval_s5_01_action_summary.json:seed-anvil-eval-s5-01-001"
  "anvil_eval_s5_01_en_action_summary.json:seed-anvil-eval-s5-01-en-001"
  "anvil_eval_s6_04_action_summary.json:seed-anvil-eval-s6-04-001"
  "anvil_eval_sp01_action_summary.json:seed-anvil-eval-sp01-codename-001"
)

echo "=== Seeding expanded eval scenario memories (multilingual) ==="
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

echo "=== Seeding common cross-repo memories ==="
"$SCRIPT_DIR/seed_common_seeds.sh"
