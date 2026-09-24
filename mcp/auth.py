from hashlib import sha256
import hmac
import json
from pathlib import Path

from fastmcp.server.auth.auth import AccessToken, TokenVerifier


class HashedTokenVerifier(TokenVerifier):
    def __init__(self, clients, *, required_scopes=None):
        super().__init__(required_scopes=required_scopes)
        self._clients = tuple(clients)

    @classmethod
    def from_file(cls, path, *, required_scopes=None):
        data = json.loads(Path(path).read_text())
        if data.get("version") != 1:
            raise ValueError("unsupported client token file version")

        clients = []
        seen_ids = set()
        seen_hashes = set()
        for raw in data.get("clients", []):
            client_id = raw["client_id"]
            token_hash = raw["token_sha256"].lower()
            scopes = list(raw.get("scopes", []))
            enabled = bool(raw.get("enabled", True))
            if client_id in seen_ids:
                raise ValueError(f"duplicate client_id: {client_id}")
            if token_hash in seen_hashes:
                raise ValueError("duplicate client token hash")
            if len(token_hash) != 64:
                raise ValueError(f"invalid token hash for {client_id}")
            int(token_hash, 16)

            seen_ids.add(client_id)
            seen_hashes.add(token_hash)
            clients.append(
                {
                    "client_id": client_id,
                    "token_hash": token_hash,
                    "scopes": scopes,
                    "enabled": enabled,
                }
            )

        if not clients:
            raise ValueError("client token file contains no clients")
        return cls(clients, required_scopes=required_scopes)

    async def verify_token(self, token):
        presented = sha256(token.encode()).hexdigest()
        for client in self._clients:
            if not client["enabled"]:
                continue
            if not hmac.compare_digest(
                presented,
                client["token_hash"],
            ):
                continue
            token_scopes = set(client["scopes"])
            if self.required_scopes and not set(
                self.required_scopes
            ).issubset(token_scopes):
                return None
            return AccessToken(
                token=token,
                client_id=client["client_id"],
                scopes=client["scopes"],
                claims={"client_id": client["client_id"]},
            )
        return None
