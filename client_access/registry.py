"""Strict token registry with per-request, atomic-replacement-aware hot reload."""
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import re
import stat
import threading

CAPABILITIES = frozenset({'llm', 'embeddings', 'reranker', 'ocr', 'stt', 'tts'})
TRANSPORTS = frozenset({'gateway', 'mcp'})
SCOPES = CAPABILITIES | TRANSPORTS
MAX_REGISTRY_BYTES = 2 * 1024 * 1024
MAX_CLIENTS = 4096
ID_PATTERN = re.compile(r'[a-z0-9][a-z0-9._-]{0,63}\Z')
HASH_PATTERN = re.compile(r'[0-9a-fA-F]{64}\Z')


class RegistryUnavailable(RuntimeError):
    """Current authorization configuration cannot safely be used."""


@dataclass(frozen=True)
class ClientIdentity:
    client_id: str
    scopes: frozenset[str]


def validate_scopes(value):
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError('scopes must be a list of strings')
    if len(value) != len(set(value)) or set(value) - SCOPES:
        raise ValueError('unknown or duplicate scope')
    if not set(value) & TRANSPORTS:
        raise ValueError('at least one transport scope is required')
    if 'mcp' in value and 'gateway' not in value:
        raise ValueError('mcp requires gateway scope for forwarded requests')
    return sorted(value)


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('invalid administrative timestamp')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('administrative timestamp requires timezone')
    return value


def validate_registry(data):
    if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] not in (1, 2):
        raise ValueError('unsupported registry version')
    if set(data) - {'version', 'clients', 'revision', 'updated_at'}:
        raise ValueError('unknown registry field')
    rows = data.get('clients')
    if not isinstance(rows, list) or len(rows) > MAX_CLIENTS:
        raise ValueError('invalid registry client list')
    revision = data.get('revision', 0)
    if type(revision) is not int or revision < 0:
        raise ValueError('invalid registry revision')
    seen_ids, seen_hashes, clients = set(), set(), []
    fields = {'client_id', 'token_sha256', 'scopes', 'enabled', 'created_at',
              'updated_at', 'rotated_at', 'revoked_at', 'owner', 'purpose'}
    for raw in rows:
        if not isinstance(raw, dict) or set(raw) - fields:
            raise ValueError('unknown client field or invalid client')
        client_id, digest = raw.get('client_id'), raw.get('token_sha256')
        if not isinstance(client_id, str) or not ID_PATTERN.fullmatch(client_id):
            raise ValueError('invalid client_id')
        if not isinstance(digest, str) or not HASH_PATTERN.fullmatch(digest):
            raise ValueError('invalid token SHA-256')
        digest = digest.lower()
        if client_id in seen_ids or digest in seen_hashes:
            raise ValueError('duplicate client identity or token digest')
        enabled = raw.get('enabled', True) if data['version'] == 1 else raw.get('enabled')
        if type(enabled) is not bool:
            raise ValueError('enabled must be a boolean')
        row = dict(raw, client_id=client_id, token_sha256=digest,
                   enabled=enabled, scopes=validate_scopes(raw.get('scopes')))
        for field in ('created_at', 'updated_at', 'rotated_at', 'revoked_at'):
            if field in row:
                _timestamp(row[field])
        if row.get('revoked_at') and enabled:
            raise ValueError('revoked clients cannot be enabled')
        for field in ('owner', 'purpose'):
            value = row.get(field, '')
            if not isinstance(value, str) or len(value) > 512 or any(ord(c) < 32 for c in value):
                raise ValueError('invalid client metadata')
        clients.append(row); seen_ids.add(client_id); seen_hashes.add(digest)
    result = dict(data, clients=clients, revision=revision)
    if 'updated_at' in result:
        _timestamp(result['updated_at'])
    return result


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON key')
        value[key] = item
    return value


def _fingerprint(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def _read(path):
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), 'rb') as f:
        before = os.fstat(f.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_REGISTRY_BYTES:
            raise ValueError('registry must be a bounded regular file')
        raw = f.read(MAX_REGISTRY_BYTES + 1)
        after = os.fstat(f.fileno())
    if len(raw) > MAX_REGISTRY_BYTES or _fingerprint(before) != _fingerprint(after):
        raise ValueError('registry changed during read or exceeds limit')
    data = json.loads(raw, object_pairs_hook=_unique_object)
    return validate_registry(data), _fingerprint(after)


def read_registry(path):
    return _read(Path(path))[0]


class TokenStore:
    """No stale-cache fallback: a broken current file denies subsequent requests.

    Mount the parent directory, not a single file, into containers. Authorization
    checks the path on each call; already admitted inference is not cancelled.
    """
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._stamp = None
        self._clients = ()
        self._refresh()

    @classmethod
    def from_file(cls, path):
        return cls(path)

    def _refresh(self):
        with self._lock:
            try:
                s = self.path.lstat()
                if not stat.S_ISREG(s.st_mode):
                    raise ValueError('registry is not a regular file')
                stamp = _fingerprint(s)
                if stamp != self._stamp:
                    data, loaded_stamp = _read(self.path)
                    self._clients = tuple(data['clients'])
                    self._stamp = loaded_stamp
                return self._clients
            except (OSError, ValueError, TypeError, RecursionError):
                self._clients = ()
                self._stamp = None
                raise RegistryUnavailable('client registry unavailable') from None

    def check_ready(self):
        self._refresh()

    def authenticate(self, authorization, *, required_scope=None):
        clients = self._refresh()
        if not isinstance(authorization, str) or len(authorization) > 4096:
            return None
        scheme, sep, token = authorization.partition(' ')
        if not sep or scheme.lower() != 'bearer' or not token or any(c.isspace() for c in token):
            return None
        presented = sha256(token.encode()).hexdigest()
        for row in clients:
            if hmac.compare_digest(presented, row['token_sha256']):
                scopes = frozenset(row['scopes'])
                if not row['enabled'] or row.get('revoked_at'):
                    return None
                if required_scope is not None and required_scope not in scopes:
                    return None
                return ClientIdentity(row['client_id'], scopes)
        return None
