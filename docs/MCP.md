# MCP integration

MCP remains optional. The core interface is still the FastAPI REST Gateway on port `8090`, and the Dispatcher remains the only component that controls GPU engines.

The repository now includes a small **FastMCP** adapter under `mcp/` for agent frameworks that speak MCP, such as OpenClaw, GolemBot/OpenCode, and other MCP-capable clients.

## Architecture

```text
OpenClaw / GolemBot / other MCP client
                |
                | Streamable HTTP MCP
                v
          FastMCP :8091/mcp
                |
                | REST
                v
          Gateway :8090
                |
                v
          Dispatcher :8092
                |
                v
          GPU engines
```

FastMCP has no Docker socket and does not call the Dispatcher directly. It only calls the same Gateway REST endpoints available to any other client.

## What is exposed as a tool

The MCP adapter exposes auxiliary capabilities:

- `read_document` — OCR for PDFs and images
- `transcribe_audio` — speech-to-text
- `generate_speech` — text-to-speech, returned as base64 WAV
- `embed_text` — embeddings
- `rerank_documents` — reranking

`/v1/chat/completions` is intentionally **not** exposed as an MCP tool. Qwen should be configured as the agent's model/provider, not as a tool that recursively calls itself.

## Why the Qwen Gateway changed

For an agent to let Qwen choose tools natively, its OpenAI-compatible chat request can contain `tools`, `tool_choice`, and `parallel_tool_calls`.

The Gateway now forwards those fields unchanged to llama.cpp. It does not execute tools itself.

The expected handoff is:

```text
1. Agent sends messages + tool definitions to Qwen.
2. Gateway acquires the LLM lease and starts Qwen if needed.
3. Qwen returns a tool call.
4. Gateway releases the LLM lease; Qwen stops.
5. Agent calls the selected MCP tool.
6. FastMCP calls the Gateway.
7. Dispatcher starts the required GPU engine and stops it after inference.
8. Agent appends the tool result to the conversation.
9. Agent sends the updated conversation to Qwen.
10. Qwen starts again and continues reasoning.
```

The conversation lives in the agent harness, not in GPU VRAM, so stopping and restarting Qwen between tool calls does not inherently lose conversation state.

## Running FastMCP

The MCP service uses the existing external Docker network `ai-services-internal` and calls `http://ai-gateway:8090` internally.

```bash
cd /opt/ai-services/mcp
docker compose build
docker compose up -d
```

By default Compose publishes MCP only on loopback:

```text
127.0.0.1:8091 -> ai-mcp:8091
```

The Streamable HTTP endpoint is:

```text
http://127.0.0.1:8091/mcp
```

For a client on another machine, bind explicitly to a trusted interface instead of exposing it to every interface. For example, if the host has a trusted VPN/Tailscale address:

```bash
MCP_BIND_ADDRESS=<trusted-interface-ip> docker compose up -d
```

Then configure the MCP client with:

```text
http://<trusted-interface-ip>:8091/mcp
```

Authentication is not added by this reference adapter. If the endpoint leaves a trusted private network, place appropriate authentication and TLS controls in front of it.

## File tools and remote clients

A remote MCP server cannot safely assume that a path such as `/home/user/invoice.pdf` exists on its own filesystem. Therefore `read_document` and `transcribe_audio` accept:

- `filename`
- `content_base64`
- `content_type`

The agent or its local harness must read the file and send its bytes as base64. This is less magical but works consistently whether the agent and GPU server are on the same machine or different machines.

## Verification

CI verifies:

- Gateway unit tests, including tool-field forwarding;
- MCP proxy unit tests;
- MCP Docker image build;
- MCP Compose syntax;
- the existing Dispatcher/Gateway tests and builds.

CI does **not** have the RTX 3080 or model weights. After deployment, perform one live end-to-end check where Qwen emits a tool call, the LLM lease is released, a GPU tool runs, and Qwen resumes with the returned result.
