# Publication privacy rules

The public repository is a curated reference implementation, not a mirror of a private homelab repository.

Do not add:

- private or VPN IP addresses;
- LAN topology or unrelated infrastructure details;
- private hostnames, VM identifiers, or hypervisor inventory;
- personal usernames, email addresses, account identifiers, or home-directory paths;
- API keys, tokens, passwords, certificates, or private keys;
- signed download URLs;
- model weights or private model caches.

Generic application names such as `ai-gateway`, `ai-dispatcher`, `ai-llm`, and `/opt/ai-services` are part of the reference application contract and are not private deployment identifiers.

Before a public release, review the full diff and run the privacy scan in `VERIFY.md`.
