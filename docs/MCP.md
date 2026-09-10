# MCP integration

MCP is not required to use `single-gpu-ai-services`.

The core interface is the FastAPI REST/OpenAPI Gateway on port `8090`. That keeps the GPU lifecycle system independent from any one agent framework or MCP implementation.

## Recommended architecture

```text
MCP-capable client
      |
      v
external REST/OpenAPI-to-MCP adapter
      |
      v
AI Services Gateway :8090
      |
      v
Dispatcher + GPU engines
```

An adapter can expose selected Gateway endpoints as MCP tools without giving the MCP process direct Docker or GPU lifecycle access.

## Why MCP is external

Keeping MCP outside the core avoids:

- duplicating the existing REST API;
- coupling GPU orchestration to a particular agent framework;
- giving another process Docker socket access;
- making non-MCP clients depend on MCP.

Use an established OpenAPI/REST-to-MCP adapter if your client requires MCP, or write a thin adapter that calls the documented Gateway endpoints.

The MCP adapter should call the Gateway only. It should not call `docker`, mount `/var/run/docker.sock`, or bypass the Dispatcher.
