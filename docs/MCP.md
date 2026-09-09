# MCP integration

MCP is intentionally **not** part of the `single-gpu-ai-services` core.

The canonical interface is the REST/OpenAPI Gateway on port `8090`.

This keeps the GPU lifecycle/orchestration layer independent of any particular agent harness and lets the same service be used by scripts, applications, bots, workflow systems, or agent frameworks.

## Using MCP anyway

MCP-capable clients can place an external adapter in front of the REST/OpenAPI API:

```text
MCP client / agent
      |
      v
external MCP adapter
      |
      v
AI Services Gateway REST/OpenAPI
      |
      v
GPU Dispatcher
      |
      v
engines
```

Frameworks such as FastMCP can create MCP tools from REST/OpenAPI interfaces, and REST-to-MCP proxy projects can provide a similar adapter layer.

The adapter should call the Gateway, not the Dispatcher and not Docker directly.

## Why MCP is external

Bundling MCP into the core would duplicate an integration layer that already has mature implementations and would couple the project to a protocol that is not necessary for ordinary REST clients.

Keeping it separate also preserves the security boundary:

```text
client integration layer
  -> Gateway
      -> Dispatcher with Docker control
```

## Tool design consideration

Not every REST endpoint necessarily makes a good model-facing MCP tool. For example:

- returning a full embedding vector can waste model context
- uploading local binary files requires an MCP client/server file-transfer design
- returning generated audio is client-dependent

A production MCP adapter may therefore expose higher-level tools rather than mechanically converting every REST endpoint one-for-one.
