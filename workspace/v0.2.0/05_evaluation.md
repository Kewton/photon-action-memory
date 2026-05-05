# 05. Evaluation Plan

## 1. Evaluation Goal

v0.2.0 should prove that Context Firewall improves coding-agent loops by reducing context pollution and token cost without reducing task success.

The main comparison is:

| Condition | Description |
|-----------|-------------|
| A | no memory |
| B | full transcript context |
| C | static summary memory |
| D | retrieval memory |
| E | PHOTON Action Memory summary-only |
| F | PHOTON Action Memory summary + evidence-on-demand |

Expected best configuration: **F. summary + evidence-on-demand**

## 2. Core Metrics from v0.1.0

Continue to measure:

- `first_useful_file_hit_rate`
- `tool_call_reduction`
- `repeated_exploration_rate`
- `test_build_time_to_first`
- `failed_action_retry_rate`
- `context_evidence_precision`
- `fail_open_incident_count`

## 3. New v0.2.0 Metrics

### Context pollution metrics

| Metric | Description |
|--------|-------------|
| `raw_tool_tokens_in_prompt` | Tokens from raw tool stdout/stderr in prompt |
| `summary_tokens_in_prompt` | Tokens from ActionSummary in prompt |
| `context_pack_tokens` | Total ContextPack token count |
| `tokens_saved_vs_raw` | Tokens saved compared to raw tool output |
| `tokens_saved_vs_full_transcript` | Tokens saved compared to full transcript |
| `context_pollution_rate` | Rate of raw context leaking into prompt |
| `duplicate_context_rate` | Rate of duplicate context items admitted |
| `stale_summary_incidents` | Count of stale summaries admitted |
| `ungrounded_fact_rate` | Facts without evidence_id in prompt |
| `hypothesis_as_fact_rate` | Hypotheses rendered as facts |

### Summary quality metrics

| Metric | Description |
|--------|-------------|
| `summary_fidelity` | Claims supported by linked evidence_ids |
| `evidence_grounding_rate` | prompt_visible_fact_count_with_evidence / prompt_visible_fact_count |
| `evidence_reconstructability` | Evidence can be retrieved and expanded |
| `fact_hypothesis_separation_score` | Facts and hypotheses kept separate |
| `failed_action_classification_accuracy` | Failed actions classified correctly |
| `avoid_guidance_precision` | Avoid guidance correctly applied |
| `summary_staleness_detection_accuracy` | Stale summaries correctly detected |

### Evidence expansion metrics

| Metric | Description |
|--------|-------------|
| `evidence_expansion_precision` | Expanded evidence was actually needed |
| `evidence_expansion_recall` | Needed evidence was expandable |
| `detail_needed_but_missing_rate` | Agent needed detail but no expandable evidence existed |
| `unnecessary_expansion_rate` | Evidence expanded when summary was sufficient |
| `expanded_chars_per_turn` | Average chars expanded per turn |
| `redaction_regression_count` | Redaction failures in expansion |

### Agent loop metrics

| Metric | Description |
|--------|-------------|
| `repeated_search_rate` | Rate of repeated search actions |
| `repeated_read_rate` | Rate of repeated file reads |
| `repeated_failed_command_rate` | Rate of repeated failed commands |
| `time_to_first_useful_file` | Time until first relevant file read |
| `time_to_first_useful_test` | Time until first useful test run |
| `time_to_first_passing_test` | Time until first passing test |
| `task_success_rate` | Task completion rate |
| `human_correction_rate` | Rate of human corrections needed |
| `agent_drift_rate` | Rate of off-task agent actions |

### Local LLM metrics

| Metric | Description |
|--------|-------------|
| `prompt_tokens_per_turn` | Total prompt tokens per turn |
| `prefill_time_ms` | Prefill latency in milliseconds |
| `decode_tokens_per_second` | Decode throughput |
| `peak_vram_mb` | Peak VRAM usage in MB |
| `cpu_fallback_rate` | Rate of GPU→CPU fallback |
| `context_length_used` | Fraction of context window used |
| `model_size` | Model parameter count |
| `quantization` | Quantization format |
| `local_inference_backend` | Backend (llama.cpp, vllm, etc.) |

## 4. Evaluation Modes

### Offline replay

Use fixed sanitized fixtures.

```
Input:   historical agent event logs
Replay:  feed events to sidecar
         generate ActionSummary
         generate ContextPack
         compare with actual next action and outcome
Output:  aggregate metrics only
```

Do not include raw logs in reports.

### Shadow-mode

Agent receives ContextPack / suggestions but is not forced to use them.

Record:

- `request_id`
- `context_pack_id`
- admitted item ids
- omitted item ids
- expanded evidence ids
- actual next action
- suggestion match
- ignored reason
- outcome
- latency
- token usage

### Canary

Only low-risk context injection is allowed.

**Allowed:**

- read candidates
- search query candidates
- test command candidates
- avoid repeated search/read warnings
- summary-only memory

**Denied:**

- destructive shell command
- edit auto-approval
- security-sensitive operation
- raw full stdout injection
- raw full stderr injection

## 5. Acceptance Criteria

### Minimum acceptance

- ContextPack can be generated without PHOTON model.
- `raw_tool_tokens_in_prompt` is near zero under default policy.
- `tokens_saved_vs_full_transcript` is measurable.
- `summary_fidelity` can be computed on fixtures.
- Stale summaries are omitted by default.
- Sidecar remains fail-open.

### Target acceptance

- `repeated_exploration_rate` decreases versus no memory.
- `failed_action_retry_rate` decreases versus no memory.
- `prompt_tokens_per_turn` decreases versus full transcript.
- `task_success_rate` does not decrease versus full transcript.
- `evidence_expansion_precision` is high enough to justify expansions.
- summary + evidence-on-demand outperforms summary-only on detail-heavy tasks.

### Stretch acceptance

- local LLM `prefill_time_ms` decreases versus full transcript.
- `peak_vram_mb` decreases or remains stable under long sessions.
- Smaller local models become usable on tasks that previously required larger context.
- PHOTON context scoring beats deterministic fallback.

## 6. Baselines

Required baselines:

1. No memory
2. Full transcript
3. Static session summary
4. Lexical retrieval
5. Vector retrieval, if available
6. Deterministic ActionSummary fallback
7. PHOTON Action Memory without Context Admission
8. PHOTON Action Memory with Context Firewall

## 7. Metric Definitions

### raw_tool_tokens_in_prompt

Number of prompt tokens that originate from raw tool stdout/stderr, raw grep output, raw build output, or raw file content.

**Target:** default policy: approximately 0

### tokens_saved_vs_raw

```
estimated_raw_tokens - context_pack_tokens
```

### summary_fidelity

Ratio of summary claims that are supported by linked evidence_ids.

### evidence_grounding_rate

```
prompt_visible_fact_count_with_evidence_id / prompt_visible_fact_count
```

### hypothesis_as_fact_rate

```
hypothesis_claims_rendered_as_fact / hypothesis_claims
```

### detail_needed_but_missing_rate

```
turns_where_agent_needed_detail_but_context_pack_had_no_expandable_evidence
/
turns_where_detail_was_needed
```

## 8. Eval Report Shape

Eval reports should be aggregate-only.

```json
{
  "schema_version": "action-memory.eval.v0.2",
  "run_id": "eval_20260430_001",
  "dataset": {
    "name": "sanitized_anvil_shadow_fixture",
    "split": "test",
    "num_sessions": 20,
    "num_turns": 400
  },
  "conditions": [
    "no_memory",
    "full_transcript",
    "summary_only",
    "summary_plus_evidence"
  ],
  "metrics": {
    "summary_plus_evidence": {
      "task_success_rate": 0.0,
      "prompt_tokens_per_turn": 0.0,
      "raw_tool_tokens_in_prompt": 0.0,
      "tokens_saved_vs_full_transcript": 0.0,
      "repeated_exploration_rate": 0.0,
      "failed_action_retry_rate": 0.0,
      "summary_fidelity": 0.0
    }
  },
  "privacy": {
    "contains_raw_logs": false,
    "contains_prompts": false,
    "contains_tool_outputs": false
  }
}
```
