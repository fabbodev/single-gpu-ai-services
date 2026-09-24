from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
from pathlib import Path


@dataclass(frozen=True)
class ClientIdentity:
    client_id: str
    scopes: frozenset[str]


class ClientTokenStore:
    def __init__(self, clients):
        self._clients = tuple(clients)

    @classmethod
    def from_file(cls, path):
        data = json.loads(Path(path).read_text())
        if data.get("version") != 1:
            raise ValueError("unsupported client token file version")

        clients = []
        seen_ids = set()
        seen_hashes = set()
        for raw in data.get("clients", []):
            client_id = raw["client_id"]
            token_hash = raw["token_sha256"].lower()
            scopes = frozenset(raw.get("scopes", []))
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
        return cls(clients)

    def authenticate(self, authorization, *, required_scope):
        if not authorization:
            return None
        scheme, sep, token = authorization.partition(" ")
        if sep != " " or scheme.lower() != "bearer" or not token:
            return None

        presented = sha256(token.encode()).hexdigest()
        for client in self._clients:
            if not client["enabled"]:
                continue
            if not hmac.compare_digest(
                presented,
                client["token_hash"],
            ):
                continue
            if required_scope not in client["scopes"]:
                return None
            return ClientIdentity(
                client_id=client["client_id"],
                scopes=client["scopes"],
            )
        return None
