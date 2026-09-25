"""Credential registry security and atomic-reload contracts (synthetic tokens)."""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

TOKEN = "synthetic-test-token-never-a-production-secret"
ALL = ["gateway", "mcp", "llm", "embeddings", "reranker", "ocr", "stt", "tts"]


def registry(scopes=None):
    return {"version": 2, "clients": [{"client_id": "test-client",
        "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
        "scopes": scopes or ALL, "enabled": True}]}


def replace(path, data):
    tmp = path.with_suffix(".next")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def store(path):
    from client_access.registry import TokenStore
    return TokenStore.from_file(path)


def test_registry_module_exists():
    assert Path(__file__).resolve().parents[1].joinpath("client_access/registry.py").is_file()


def test_authentication_and_capabilities(tmp_path):
    p = tmp_path / "registry.json"; replace(p, registry(["gateway", "embeddings"]))
    s = store(p)
    identity = s.authenticate("Bearer " + TOKEN)
    assert identity.client_id == "test-client"
    assert identity.scopes == frozenset(["gateway", "embeddings"])
    assert s.authenticate("Bearer bad") is None
    assert s.authenticate("Basic " + TOKEN) is None
    assert s.authenticate(None) is None
    assert s.authenticate("Bearer " + TOKEN, required_scope="llm") is None


def test_atomic_revocation_and_reenable_without_new_store(tmp_path):
    p = tmp_path / "registry.json"; data = registry(); replace(p, data); s = store(p)
    assert s.authenticate("Bearer " + TOKEN)
    data["clients"][0]["enabled"] = False; replace(p, data)
    assert s.authenticate("Bearer " + TOKEN) is None
    data["clients"][0]["enabled"] = True; replace(p, data)
    assert s.authenticate("Bearer " + TOKEN)


def test_atomic_rotation_invalidates_old_token(tmp_path):
    p = tmp_path / "registry.json"; data = registry(); replace(p, data); s = store(p)
    new = "another-synthetic-token"
    data["clients"][0]["token_sha256"] = hashlib.sha256(new.encode()).hexdigest(); replace(p, data)
    assert s.authenticate("Bearer " + TOKEN) is None
    assert s.authenticate("Bearer " + new)


@pytest.mark.parametrize("broken", ["missing", "json", "shape", "symlink"])
def test_bad_current_registry_fails_closed_then_recovers(tmp_path, broken):
    from client_access.registry import RegistryUnavailable
    p = tmp_path / "registry.json"; replace(p, registry()); s = store(p)
    assert s.authenticate("Bearer " + TOKEN)
    if broken == "missing": p.unlink()
    elif broken == "json": p.write_text("{incomplete")
    elif broken == "shape": replace(p, {"version": 2, "clients": "not-list"})
    else:
        target = tmp_path / "other"; target.write_text(p.read_text()); p.unlink(); p.symlink_to(target)
    with pytest.raises(RegistryUnavailable): s.authenticate("Bearer " + TOKEN)
    replace(p, registry()); assert s.authenticate("Bearer " + TOKEN)


def test_empty_registry_denies_everyone(tmp_path):
    p = tmp_path / "registry.json"; replace(p, {"version": 2, "clients": []})
    assert store(p).authenticate("Bearer " + TOKEN) is None


@pytest.mark.parametrize("change", [
    lambda d: d.update(version=True),
    lambda d: d.update(version=3),
    lambda d: d["clients"][0].update(enabled="false"),
    lambda d: d["clients"][0].update(client_id="unsafe\nlog"),
    lambda d: d["clients"][0].update(token_sha256="x" * 64),
    lambda d: d["clients"][0].update(scopes=["gateway", "admin"]),
    lambda d: d["clients"][0].update(scopes="gateway"),
    lambda d: d["clients"][0].update(scopes=["gateway", "gateway"]),
    lambda d: d["clients"][0].update(scopes=["mcp", "llm"]),
    lambda d: d["clients"][0].update(token="plaintext-is-not-permitted"),
    lambda d: d["clients"].append(copy.deepcopy(d["clients"][0])),
    lambda d: d["clients"].append({**d["clients"][0], "client_id": "different-id"}),
    lambda d: d["clients"][0].update(revoked_at="2026-09-25T00:00:00Z", enabled=True),
])
def test_invalid_or_ambiguous_schema_rejected(tmp_path, change):
    from client_access.registry import RegistryUnavailable
    p = tmp_path / "registry.json"; data = registry(); change(data); replace(p, data)
    with pytest.raises(RegistryUnavailable): store(p)


def test_duplicate_json_keys_rejected(tmp_path):
    from client_access.registry import RegistryUnavailable
    p = tmp_path / "registry.json"; p.write_text('{"version":2,"version":2,"clients":[]}')
    with pytest.raises(RegistryUnavailable): store(p)


def test_transport_alone_does_not_grant_capabilities(tmp_path):
    p = tmp_path / "registry.json"; data = registry(["gateway"]); data["version"] = 1; replace(p, data)
    identity = store(p).authenticate("Bearer " + TOKEN)
    assert "llm" not in identity.scopes


def test_oversized_registry_rejected(tmp_path):
    from client_access.registry import RegistryUnavailable
    p = tmp_path / "registry.json"; p.write_text(" " * (2 * 1024 * 1024 + 1))
    with pytest.raises(RegistryUnavailable): store(p)
