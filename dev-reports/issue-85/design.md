# Issue #85 Design

## Goal

Prevent low-value Anvil summaries from becoming prompt-visible when they mostly
repeat the current task or encourage premature termination. Keep meta-information
summaries, especially verifier or repo-specific policy guidance, admissible.

## Approach

- Add a small deterministic quality gate before ContextPack admission.
- Compare the current task text with each summary's prompt-visible fields.
- Reject high-overlap summaries when they add little new information and contain
  direct next-step hints likely to shortcut exploration.
- Keep verifier/meta-information summaries even when they contain some task
  vocabulary.
- Record the decision in both admission decisions and omitted items so Anvil can
  inspect why a summary was not injected.

## Scope

- Implement the gate in the context packing path, where prompt visibility is
  decided.
- Pass task text from `POST /v1/context/pack` into the pack builder.
- Add focused regression tests for S2-03-style low-value guidance and S5-01-style
  meta-information guidance.

