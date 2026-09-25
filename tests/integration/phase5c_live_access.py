#!/usr/bin/env python3
"""Opt-in live credential lifecycle acceptance; emits no plaintext credentials.

Run from an operator environment with write access to the specified v2 registry.
Only a unique temporary client is administered. Corrupt-file recovery is a
separate explicit opt-in maintenance test; it briefly blocks all new requests.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def request(base, key, path='/v1/models', payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(base.rstrip('/') + path, data=data,
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, None


def denial_matches(exc, wire_status):
    if wire_status not in (401, 403):
        return False
    # MCP SDK 2.2 intentionally flattens some non-2xx HTTP responses to
    # INTERNAL_ERROR without retaining HTTP status. Require a separate wire
    # authorization failure rather than accepting every generic MCP failure.
    if (type(exc).__name__ == 'MCPError' and getattr(exc, 'code', None) == -32603
            and str(exc) == 'Server returned an error response'):
        return True
    return bool(re.search(r'401|403|unauthoriz|invalid token|insufficient|permission|authentication', str(exc), re.I))


async def exercise(args):
    from client_access.admin import atomic_write, registry_lock
    from client_access.registry import read_registry
    from fastmcp import Client
    from fastmcp.client.auth.bearer import BearerAuth

    client_id = 'phase5c-check-' + uuid4().hex[:12]
    cli = [sys.executable, str(ROOT / 'scripts/ai-client'), '--registry', str(args.registry)]
    original = read_registry(args.registry)['clients']
    results = []
    created = False

    def record(name):
        results.append(name)
        print(json.dumps({'test': name, 'status': 'PASS'}), flush=True)

    def control(action, *extra, success=True):
        out = subprocess.run(cli + [action, client_id, *map(str, extra)],
                             capture_output=True, text=True, timeout=15)
        assert (out.returncode == 0) == success, 'CLI ' + action + ' result mismatch'
        return out

    def expect(key, code, path='/v1/models', payload=None):
        actual, data = request(args.gateway_url, key, path, payload)
        assert actual == code, f'HTTP status {actual}, expected {code}'
        return data

    async def embed(client):
        value = await client.call_tool('embed_text', {'input': 'scoped client validation'}, timeout=300)
        assert not value.is_error
        assert len(value.structured_content['data'][0]['embedding']) == 1024

    async def expect_mcp_denied(client, key):
        try:
            value = await client.call_tool('embed_text', {'input': 'must be denied'}, timeout=20)
        except Exception as exc:
            # A timeout/network failure does not count as authorization success.
            req = urllib.request.Request(args.mcp_url, headers={
                'Authorization': 'Bearer ' + key,
                'Accept': 'application/json, text/event-stream'})
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    wire_status = response.status
            except urllib.error.HTTPError as error:
                wire_status = error.code
            assert denial_matches(exc, wire_status), type(exc).__name__
        else:
            assert value.is_error, 'MCP unexpectedly accepted revoked/limited access'

    with tempfile.TemporaryDirectory(prefix='ai-client-delivery-') as temp:
        key_file = Path(temp) / 'first.token'
        next_file = Path(temp) / 'next.token'
        try:
            control('create', '--scopes', 'gateway,mcp,embeddings', '--token-file', key_file)
            created = True
            key = key_file.read_text().strip()
            models = expect(key, 200)
            assert [m['id'] for m in models['data']] == ['bge-m3']
            expect(key, 403, '/v1/chat/completions', {'model': 'qwen3-8b', 'messages': [{'role': 'user', 'content': 'denied'}]})
            record('scoped-discovery-and-rest-denial')
            async with Client(args.mcp_url, auth=BearerAuth(key), timeout=300) as client:
                await embed(client)
                record('live-mcp-embedding')
                control('disable')
                expect(key, 401)
                await expect_mcp_denied(client, key)
                record('revoked-access-denied-in-established-mcp-session')
            control('enable')
            expect(key, 200)
            control('set-scopes', '--scopes', 'gateway,mcp,llm')
            expect(key, 403, '/v1/embeddings', {'model': 'bge-m3', 'input': 'denied'})
            record('reenable-and-live-scope-change')
            control('set-scopes', '--scopes', 'gateway,mcp,embeddings')
            control('rotate', '--token-file', next_file)
            next_key = next_file.read_text().strip()
            expect(key, 401); expect(next_key, 200)
            record('rotation-invalidates-old-key')
            if args.exercise_corruption:
                with registry_lock(args.registry):
                    before = read_registry(args.registry)
                    temp_registry = args.registry.parent / ('.invalid-' + uuid4().hex)
                    try:
                        fd = os.open(temp_registry, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
                        with os.fdopen(fd, 'w') as f: f.write('{invalid')
                        os.replace(temp_registry, args.registry)
                        expect(next_key, 503)
                    finally:
                        atomic_write(args.registry, before)
                        if temp_registry.exists(): temp_registry.unlink()
                expect(next_key, 200)
                record('invalid-registry-fails-closed-and-recovers')
            async with Client(args.mcp_url, auth=BearerAuth(next_key), timeout=300) as client:
                await embed(client)
            control('revoke'); expect(next_key, 401)
            control('enable', success=False)
            record('permanent-revocation')
        finally:
            if created:
                control('revoke')
            after = read_registry(args.registry)['clients']
            assert [row for row in after if row['client_id'] != client_id] == original, 'Unrelated client policy changed'
    print(json.dumps({'status': 'PASS', 'client_id': client_id, 'client_revoked': True,
                      'checks': results, 'unrelated_clients_unchanged': True}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--exercise-corruption', action='store_true')
    parser.add_argument('--registry', type=Path, default=Path('/etc/ai-services/clients/client-tokens.json'))
    parser.add_argument('--gateway-url', default='http://127.0.0.1:8090')
    parser.add_argument('--mcp-url', default='http://127.0.0.1:8091/mcp')
    args = parser.parse_args()
    if not args.execute:
        print('PLAN ONLY: create temporary client, REST/MCP permissions, disable/enable, rotate/revoke; explicit execution required.')
        return
    asyncio.run(exercise(args))


if __name__ == '__main__':
    main()
