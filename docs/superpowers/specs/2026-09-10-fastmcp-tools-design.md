# FastMCP Tool Adapter Design

## Goal

Expose selected GPU capabilities to MCP-capable agents such as OpenClaw and GolemBot without changing the Dispatcher ownership model or giving the MCP process Docker access.

## Architecture

```text
OpenClaw / GolemBot / other MCP client
                |
                | Streamable HTTP MCP
                v
          FastMCP adapter :8091
                |
                | REST
                v
          Gateway :8090
                |
                v
          Dispatcher :8092
                |
                v
          GPU engine containers
```

FastMCP is an optional adapter. The REST Gateway remains the stable public API and the Dispatcher remains the only component allowed to control engine containers.

## MCP tools

Expose only auxiliary capabilities:

- `read_document(filename, content_base64, content_type)` -> Gateway `/v1/documents/read`
- `transcribe_audio(filename, content_base64, content_type, language)` -> Gateway `/v1/audio/transcriptions`
- `generate_speech(text)` -> Gateway `/v1/audio/speech`, returned as base64 WAV
- `embed_text(input)` -> Gateway `/v1/embeddings`
- `rerank_documents(query, documents)` -> Gateway `/v1/rerank`

Do not expose `/v1/chat/completions` as an MCP tool. Qwen is the agent model/provider, not a tool that should recursively call itself.

## Remote file handling

The MCP server may run on a different host from the agent. Therefore file-oriented tools must not accept client-local filesystem paths. They accept base64 plus filename/content type and reconstruct a multipart request to the Gateway.

## Qwen native tool calling

The current Gateway only forwards a small allowlist of OpenAI-compatible chat fields. To permit OpenClaw/GolemBot to give Qwen tool definitions, the Gateway must also forward `tools`, `tool_choice`, and `parallel_tool_calls` when present. The Gateway must not interpret tool calls; it only forwards the request and returns the llama.cpp response.

The existing request lifecycle remains unchanged: each Qwen request acquires the LLM lease and releases it in `finally`. After Qwen returns a tool call, the LLM container is stopped, the MCP tool request can acquire another GPU service, and a later Qwen request starts the LLM again with the conversation/tool result supplied by the agent harness.

## Networking and security

- FastMCP joins `ai-services-internal` and talks only to `http://ai-gateway:8090`.
- FastMCP never mounts `/var/run/docker.sock`.
- Default host publication is loopback-only: `127.0.0.1:8091`.
- Operators who need remote MCP access should bind explicitly to a trusted VPN/Tailscale interface or place authentication/reverse proxy controls in front of it.
- The adapter contains no credentials by default.

## Runtime

Use FastMCP 4.x, which is GA as of 2026-08-31. Run Streamable HTTP on `/mcp` via `mcp.run(transport="http", host="0.0.0.0", port=8091)`.

## Testing

- Unit-test each proxy tool with an `httpx.MockTransport` or injected async client.
- Test invalid base64 before any Gateway request is attempted.
- Add a Gateway regression test proving `tools`, `tool_choice`, and `parallel_tool_calls` reach llama.cpp unchanged.
- Build the MCP Docker image and validate its Compose file in CI.
- Live Qwen -> MCP tool -> Qwen handoff remains a deployment verification step because CI has no GPU/model runtime.
