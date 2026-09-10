# Security

## Trust model

The project intentionally separates the public-facing Gateway from the Docker-controlling Dispatcher.

### Gateway

- published on host port `8090` by the reference compose file;
- does not mount `/var/run/docker.sock`;
- communicates with the Dispatcher and engines over the private Docker network.

### Dispatcher

- not published to a host port by the reference compose file;
- mounts `/var/run/docker.sock`;
- can start, inspect, and stop engine containers;
- should therefore be treated as a host-privileged component.

Access to the Docker socket is effectively equivalent to high privilege on the Docker host. Do not expose the Dispatcher directly to untrusted clients.

## Recommended exposure

Preferred pattern:

```text
trusted client / VPN / authenticated reverse proxy
                  |
                  v
             Gateway :8090
                  |
                  v
        private Docker network
                  |
             Dispatcher
                  |
              Docker socket
```

If the Gateway is exposed outside a trusted LAN or VPN, add authentication, TLS, request limits, and an appropriate reverse proxy. The reference Gateway does not implement authentication by itself.

## Secrets

Do not commit:

- Hugging Face tokens;
- API keys;
- `.env` files containing credentials;
- TLS private keys;
- SSH keys;
- signed download URLs;
- model-provider credentials.

The repository `.gitignore` excludes common secret and model file patterns, but `.gitignore` is not a security boundary. Review staged changes before every public push.

## Model files

Model weights are intentionally outside Git. Operators are responsible for obtaining them from upstream sources and complying with their licenses and terms.

## Engine ports

Most engine-to-Gateway traffic should stay on `ai-services-internal`. Some reference compose files bind development/debug ports only to `127.0.0.1`; do not change those bindings to `0.0.0.0` unless you deliberately want the backend reachable from the host network.

## Docker images and tags

Several reference engine definitions use upstream image tags. For higher-assurance production deployments, pin images by immutable digest after testing the exact version you intend to run.

## Reporting security issues

Do not place credentials, private network data, or exploitation details containing real secrets in a public issue. Use a private contact channel associated with the repository owner when appropriate.
