# Client configuration templates

These are generic templates, not preconfigured accounts. Replace the `.example.internal`
address and load `AI_SERVICES_API_KEY` privately. Review before merging with any
existing configuration. Do not overwrite a production agent or enable cloud fallback.

- `openclaw.json`: custom Chat Completions provider and Streamable HTTP MCP.
- `hermes-mcp.yaml`: add AI capabilities to a Hermes instance's existing primary LLM.
- `hermes-model.yaml`: optional wire configuration, NOT accepted for full Hermes
  agent use with the current 16K reference model; current docs require 64K for tools.
- `golem.yaml` + `opencode.json`: GolemBot delegates to OpenCode. Keep both in a
  separate bot workspace. OpenCode explicitly uses `@ai-sdk/openai-compatible`,
  not the Responses adapter. Other GolemBot engines require different protocols.

OpenClaw and Hermes use `${AI_SERVICES_API_KEY}` in MCP headers. OpenCode uses
`{env:AI_SERVICES_API_KEY}`. These are client-side substitutions, not Gateway logic.
See ../../docs/CLIENTS.md for authoritative scope and compatibility details.
