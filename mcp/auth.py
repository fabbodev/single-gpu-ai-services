"""FastMCP adapter with the same live registry used by the Gateway."""
from fastmcp.server.auth.auth import AccessToken, TokenVerifier
from client_access.registry import RegistryUnavailable, TokenStore


class HashedTokenVerifier(TokenVerifier):
    def __init__(self, store, *, required_scopes=None):
        super().__init__(required_scopes=required_scopes)
        self.store = store

    @classmethod
    def from_file(cls, path, *, required_scopes=None):
        return cls(TokenStore.from_file(path), required_scopes=required_scopes)

    async def verify_token(self, token):
        try:
            identity = self.store.authenticate('Bearer ' + token)
        except RegistryUnavailable:
            return None
        if identity is None or not set(self.required_scopes or ()).issubset(identity.scopes):
            return None
        return AccessToken(token=token, client_id=identity.client_id,
                           scopes=sorted(identity.scopes),
                           claims={'client_id': identity.client_id})
