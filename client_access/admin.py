"""Local administrator. No network endpoint and no plaintext tokens in stdout."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile

from client_access.registry import CAPABILITIES, HASH_PATTERN, ID_PATTERN, MAX_REGISTRY_BYTES, read_registry, validate_registry, validate_scopes

DEFAULT_REGISTRY = '/etc/ai-services/clients/client-tokens.json'


def now():
    return datetime.now(timezone.utc).isoformat()


def private_directory(path, *, create=False):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('an absolute path is required')
    # Do not follow a link into an unexpected secret location.
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symlink directories are not allowed')
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    s = path.stat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.geteuid() or stat.S_IMODE(s.st_mode) & 0o077:
        raise ValueError('directory must be owned by the operator with mode 0700')


@contextmanager
def registry_lock(path):
    private_directory(path.parent, create=True)
    fd = os.open(path.parent / '.ai-client.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) & 0o077:
            raise ValueError('unsafe registry lock')
        fcntl.flock(fd, fcntl.LOCK_EX)
        if path.is_symlink():
            raise ValueError('registry symlink refused')
        yield
    finally:
        os.close(fd)


def encode_registry(data):
    data = validate_registry(data)
    raw = (json.dumps(data, indent=2, sort_keys=True) + '\n').encode()
    if len(raw) > MAX_REGISTRY_BYTES:
        raise ValueError('registry exceeds the reader byte limit')
    return raw


def atomic_write(path, data):
    raw = encode_registry(data)
    fd, temp = tempfile.mkstemp(prefix='.registry-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            os.fchmod(f.fileno(), 0o400)
            f.write(raw); f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)
        dfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try: os.fsync(dfd)
        finally: os.close(dfd)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def write_token(path, token, registry):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('token output requires an absolute path')
    normalized = path.resolve(strict=False)
    registry_dir = registry.parent.resolve()
    if normalized == registry_dir or registry_dir in normalized.parents:
        raise ValueError('plaintext keys must stay outside the mounted registry directory')
    private_directory(path.parent, create=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o400)
    with os.fdopen(fd, 'w') as f:
        f.write(token + '\n'); f.flush(); os.fsync(f.fileno())


def new_digest(args, registry):
    if args.token_sha256 is not None:
        if not HASH_PATTERN.fullmatch(args.token_sha256):
            raise ValueError('token-sha256 must be a 64-hex digest, never a plaintext key')
        return args.token_sha256.lower(), None
    token = 'ai_' + secrets.token_urlsafe(32)
    return hashlib.sha256(token.encode()).hexdigest(), token


def mutate(args):
    path = Path(args.registry)
    with registry_lock(path):
        timestamp = now()
        if args.action in ('init', 'migrate'):
            if path.exists(): raise ValueError('refusing to overwrite an existing registry')
            data = {'version': 2, 'revision': 0, 'clients': []}
            if args.action == 'migrate':
                old = read_registry(args.from_file)
                if old['version'] != 1: raise ValueError('migration requires a version 1 source')
                data['clients'] = old['clients']
                for row in data['clients']:
                    # Preserve explicit capability policies; only legacy transport-only
                    # entries receive the previous all-capability behavior.
                    if not set(row['scopes']) & CAPABILITIES:
                        row['scopes'] = sorted(set(row['scopes']) | CAPABILITIES)
                    row.setdefault('created_at', timestamp)
        else:
            data = read_registry(path)
            if data['version'] != 2: raise ValueError('migrate the registry to version 2 before administration')
        if args.action == 'list':
            return {'version': data['version'], 'revision': data['revision'],
                    'clients': [{k: v for k, v in x.items() if k != 'token_sha256'} for x in data['clients']]}
        token = None
        if args.action in ('create', 'rotate'):
            digest, token = new_digest(args, path)
            if any(x['token_sha256'] == digest for x in data['clients']):
                raise ValueError('token digest is already registered')
        if args.action == 'create':
            if not ID_PATTERN.fullmatch(args.client_id): raise ValueError('invalid client_id')
            if any(x['client_id'] == args.client_id for x in data['clients']): raise ValueError('client_id already exists')
            data['clients'].append({'client_id': args.client_id, 'token_sha256': digest,
                'scopes': validate_scopes(args.scopes.split(',')), 'enabled': True,
                'created_at': timestamp, 'owner': args.owner, 'purpose': args.purpose})
        elif args.action in ('rotate', 'disable', 'enable', 'revoke', 'set-scopes'):
            row = next((x for x in data['clients'] if x['client_id'] == args.client_id), None)
            if row is None: raise ValueError('client not found')
            if row.get('revoked_at') and args.action != 'revoke': raise ValueError('revoked client is permanent; create a new identity')
            if args.action == 'rotate': row.update(token_sha256=digest, rotated_at=timestamp)
            elif args.action == 'disable': row['enabled'] = False
            elif args.action == 'enable': row['enabled'] = True
            elif args.action == 'revoke': row.update(enabled=False, revoked_at=timestamp)
            else: row['scopes'] = validate_scopes(args.scopes.split(','))
            row['updated_at'] = timestamp
        data['revision'] += 1
        data['updated_at'] = timestamp
        encode_registry(data)
        # Validate before delivering any key. Exclusive output creation must succeed
        # before replacing the registry, so a delivery failure cannot lock a user out.
        if token is not None: write_token(args.token_file, token, path)
        atomic_write(path, data)
        result = {'action': args.action, 'revision': data['revision'], 'status': 'ok'}
        if getattr(args, 'client_id', None): result['client_id'] = args.client_id
        if token is not None: result['token_file'] = str(args.token_file)
        return result


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registry', default=os.environ.get('AI_CLIENT_REGISTRY', DEFAULT_REGISTRY))
    subs = p.add_subparsers(dest='action', required=True)
    subs.add_parser('init', help='create an empty deny-all v2 registry')
    m = subs.add_parser('migrate', help='explicitly preserve legacy v1 access in a new registry')
    m.add_argument('--from-file', required=True, type=Path)
    subs.add_parser('list', help='list metadata without token digests or plaintext')
    for action in ('create', 'rotate', 'disable', 'enable', 'revoke', 'set-scopes'):
        s = subs.add_parser(action); s.add_argument('client_id')
        if action in ('create', 'set-scopes'): s.add_argument('--scopes', required=True)
        if action == 'create':
            s.add_argument('--owner', default=''); s.add_argument('--purpose', default='')
        if action in ('create', 'rotate'):
            group = s.add_mutually_exclusive_group(required=True)
            group.add_argument('--token-file', type=Path, help='new exclusive 0400 delivery file outside registry directory')
            group.add_argument('--token-sha256', help='enroll a securely minted client-side token without transferring its plaintext')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    os.umask(0o077)
    try:
        result = mutate(args)
    except (OSError, ValueError, TypeError) as exc:
        print(f'ai-client: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
