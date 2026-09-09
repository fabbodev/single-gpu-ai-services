# Security

This project intentionally separates the public-facing REST Gateway from Docker lifecycle control.

## Trust boundary

The Dispatcher mounts:

```text
/var/run/docker.sock
```

Access to the Docker socket should be treated as host-equivalent administrative privilege. The Dispatcher therefore belongs on a private Docker network and should not be exposed directly to untrusted clients.

The Gateway does **not** mount the Docker socket.

Recommended traffic path:

```text
trusted client
  -> Gateway
      -> internal Dispatcher
          -> engine containers
```

## Authentication

This reference implementation does not add a built-in authentication layer to the Gateway.

If the Gateway is reachable by anything other than trusted local clients, put it behind an authentication/access-control layer appropriate for your environment before exposing it.

Do not expose the Dispatcher or engine control endpoints as a substitute for Gateway access.

## Engine exposure

The engine containers are implementation details. Some reference Compose files bind an engine port to loopback for debugging, but normal client traffic should use the Gateway.

Directly exposing engines can bypass:

- request validation
- logical GPU leasing
- the one-service-at-a-time invariant
- lifecycle cleanup

## Secrets

Do not commit:

- API keys or tokens
- registry credentials
- model-download credentials
- `.env` files containing secrets
- private keys or certificates

The repository `.gitignore` blocks common secret and model-weight file patterns, but it is not a substitute for reviewing commits.

## Model files and third-party images

Model weights are deliberately excluded from this repository. Operators are responsible for obtaining model files from their upstream sources and complying with the applicable licenses and terms.

The reference configuration also uses third-party container images. Review and pin image versions/digests according to your own supply-chain requirements before production use.

## Docker socket hardening

The current Dispatcher controls engines through Docker CLI commands over the host Docker socket. This is intentionally simple, but it means a compromise of the Dispatcher can become a compromise of the Docker host.

For higher-assurance environments, consider placing the service on a dedicated host/VM or replacing direct Docker-socket access with a more constrained lifecycle-control mechanism.

## Reporting security issues

Before opening a public issue that may contain sensitive deployment details, remove private addresses, credentials, internal hostnames, and other environment-specific information.
