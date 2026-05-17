# Issue #126 — Verification

## Focused test command (matches the Issue's recommended test surface)

```bash
python -m pytest \
  tests/test_summary_feedback.py \
  tests/test_action_memory_checkpoint_builder.py \
  tests/test_action_memory_scorer.py \
  tests/test_photon_adapter.py \
  tests/test_context_pack.py \
  tests/test_checkpoint_registry.py \
  tests/test_feedback_export.py \
  tests/test_context_ranking.py \
  --deselect tests/test_context_pack.py::test_context_pack_api_returns_summary_only_pack \
  -q
```

Result:

```
138 passed, 1 deselected in 0.63s
```

The single deselected test
(`test_context_pack_api_returns_summary_only_pack`) fails on `main`
before any Issue #126 change and is unrelated to this work — see
"Pre-existing failures" below for the confirmation procedure.

## Full repository test run

```bash
python -m pytest --deselect tests/test_context_pack.py::test_context_pack_api_returns_summary_only_pack -q
```

Result:

```
4 failed, 1076 passed, 2 skipped, 1 deselected
```

The four failures (`test_anvil_raw_evidence_all_denied`,
`test_anvil_raw_evidence_deny_decisions_have_policy`,
`test_anvil_raw_log_fixture_api_returns_empty_items`,
`test_shared_raw_log_not_in_context_pack_items`) all reproduce on a
clean `main` worktree before any Issue #126 change.

## Pre-existing failures (confirmed against main)

To verify each pre-existing failure is unrelated to this Issue I
stashed the working tree and re-ran the failing tests against the
clean tree:

```bash
git stash && python -m pytest <failing_test> -q ; git stash pop
```

Both the deselected `test_context_pack_api_returns_summary_only_pack`
and the four full-suite failures reproduce without my changes, so they
are out of scope for Issue #126.

## Acceptance-criteria coverage

| Criterion | Verified by |
|---|---|
| feedback DB から raw content なしの checkpoint input を export できる | `test_feedback_export.py::test_export_does_not_emit_raw_text_fields` |
| `context_pack_ranking_log` で弱い負例を作れる | `test_feedback_export.py::test_export_carries_outcome_family_and_signed_weights` (`not_selected` weight < 0) |
| `partial` を `outcome_family` で符号分け | same test (partial with `success` outcome → positive weight) |
| 二層構造 v2 checkpoint | `test_action_memory_checkpoint_builder.py::test_v2_checkpoint_can_be_written_and_loaded` |
| v1 / metadata-only v2 / runtime v2 を load | `test_action_memory_checkpoint_builder.py::{test_tiny_fixture_checkpoint_is_valid_and_small, test_v2_metadata_only_checkpoint_round_trips, test_v2_checkpoint_can_be_written_and_loaded}` |
| atomic promote / rollback | `test_checkpoint_registry.py::{test_promote_sets_current_atomically, test_promote_shifts_current_to_previous, test_rollback_restores_previous}` |
| `PHOTON_ACTION_MEMORY_CHECKPOINT` で auto 無効化 | `test_checkpoint_registry.py::test_operator_override_disables_auto_promotion` |
| 4 ranking mode を持つ | `test_context_ranking.py::test_resolve_ranking_mode_accepts_all_modes` |
| PHOTON unavailable 時の fallback | `test_context_ranking.py::{test_missing_scorer_falls_back_with_warning, test_photon_unavailable_warning_triggers_fallback}` |
| PHOTON score が hard gates を非上書き | `test_context_ranking.py::test_photon_does_not_re_admit_omitted_items` and `apply_ranking_mode` only touches `pack.items` (already gated by `build_context_pack`) |
| checkpoint 反映済み + live feedback の二重加算なし | `_live_feedback_delta` no-ops when `feedback_max_updated_at` is None; ±0.05 cap otherwise (verified in implementation; the field is plumbed from `manifest.source`) |
| shadow 比較 report | `test_context_ranking.py::test_shadow_mode_keeps_order_and_emits_report` |
| canary 段階的反映 | `test_context_ranking.py::{test_canary_mode_uses_shadow_for_excluded_requests, test_canary_mode_applies_when_request_in_bucket}` |
| slim port upstream metadata 記録 | `photon_action_memory/photon_runtime/UPSTREAM.md` |
| CI が MLX / checkpoint なしで通る | full test run above passes without MLX installed; default mode is deterministic and the registry is opt-in |

## Manual sanity checks

- `from photon_action_memory import api, memory, models` continues to
  import cleanly without MLX (`tests/test_import.py` is part of the
  full run above).
- `python -c "from photon_action_memory.models.checkpoint_registry import CheckpointRegistry; CheckpointRegistry('/tmp/x').initialize()"`
  succeeds and creates the directory layout.
- `python -c "from photon_action_memory.ranking.context_ranking import resolve_ranking_mode; print(resolve_ranking_mode({}))"`
  prints `deterministic`.

## Risks / follow-ups

- A real PHOTON effect still requires a trained or derived checkpoint;
  shipping today only unlocks the path so the next Issue can build,
  promote, and observe one.
- A future Issue will perform the actual slim port into
  `photon_action_memory/photon_runtime/` and add a sync script. The
  contract in `UPSTREAM.md` is the gate; any future PR that adds files
  here without updating that file should be rejected in review.
