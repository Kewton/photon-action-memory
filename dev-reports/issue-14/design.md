# Issue #14 Design: MCP / stdio adapter note

## Goal

Add a lightweight design note for non-HTTP integration paths so `photon-action-memory`
can later support stdio and MCP clients without inventing a second contract beside
the sidecar API schema.

## Shape

- Create a dedicated workspace note for the adapter policy.
- Treat `photon_action_memory.api.schema` DTOs as the canonical payload contract
  for HTTP, stdio, and MCP.
- Define HTTP as the v0.1.0 runtime surface, stdio as a future local transport
  wrapper, and MCP as a future tool/resource exposure layer over the same request,
  response, event, summary, and evaluation schemas.
- Keep privacy policy transport-neutral: adapters may only pass sanitized,
  schema-valid DTOs and must not forward raw logs, prompts, tool stdout/stderr, or
  secrets.

## Scope boundaries

This issue is documentation-only. v0.1.0 should not implement an MCP server,
stdio protocol loop, transport negotiation, editor plugin, or adapter-specific
storage. The design note should make those non-goals explicit so implementation
issues can stay focused on schema, sanitizer, sidecar, fallback ranking, and
shadow evaluation.
