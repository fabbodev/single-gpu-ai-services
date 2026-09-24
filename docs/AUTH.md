# Authentication and trusted-network exposure

The reference deployment assumes clients reach AI Services through a trusted
private network such as Tailscale. Network trust is an additional boundary,
not the client identity mechanism.

## Client authentication

Gateway and MCP require a Bearer token for application traffic.

Each bot should receive its own random token. The plaintext token is given only
to that bot/operator. AI Services stores only its SHA-256 digest in the client
registry.

Reference registry path:

```text
/etc/ai-services/secrets/client-tokens.json
```

Example structure:

```json
{
  "version": 1,
  "clients": [
    {
      "client_id": "example-bot",
      "token_sha256": "<64 hex characters>",
      "scopes": ["gateway", "mcp"],
      "enabled": true
    }
  ]
}
```

A token used through MCP needs both `mcp` and `gateway` scopes because MCP
authenticates the caller and forwards that same Bearer token to Gateway.

Gateway logs the authenticated `client_id`; it does not log the plaintext
Bearer token.

## Dispatcher authentication

Dispatcher is not published to the host. Gateway additionally authenticates
every private control request using a separate shared secret:

```text
X-AI-Internal-Token: <secret>
```

Reference secret path:

```text
/etc/ai-services/secrets/dispatcher-token
```

This token is unrelated to bot/client keys and must never be given to clients.
## Network binding

Gateway and MCP default to loopback if no bind address is supplied.

For the private deployment, set their bind addresses to the host Tailscale IP:

```text
GATEWAY_BIND_ADDRESS=<tailscale-ip>
MCP_BIND_ADDRESS=<tailscale-ip>
```

Dispatcher remains reachable only through `ai-services-internal`.

Do not publish Dispatcher or engine ports to the Internet.

## Rotation

To revoke one bot, disable or remove only that bot entry and recreate Gateway
and MCP so they reload the registry.

To rotate the Dispatcher secret, write a new secret and recreate Dispatcher
and Gateway together.

Runtime secrets live outside the Git checkout. Use a root-owned `0700`
secret directory and `0400` files. The repository also ignores `secrets/`,
`.env`, private keys, and certificates as defense in depth.

## Future Internet-facing clients

Do not expose ports 8090 or 8091 directly to the public Internet. Put an
authenticated TLS reverse proxy / edge layer in front, retain per-client
identity, and keep Dispatcher and engines private.
