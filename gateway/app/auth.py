"""Gateway adapter for the shared client identity implementation."""
from client_access.registry import ClientIdentity, RegistryUnavailable, TokenStore

ClientTokenStore = TokenStore
__all__ = ['ClientIdentity', 'ClientTokenStore', 'RegistryUnavailable']
