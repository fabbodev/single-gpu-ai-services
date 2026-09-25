"""Black-box admin tests. Never use production keys or paths."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "ai-client"


def command(p, *args, ok=True):
    result = subprocess.run([sys.executable, str(CLI), "--registry", str(p), *map(str,args)], capture_output=True, text=True, timeout=15)
    if ok: assert result.returncode == 0, result.stderr
    else: assert result.returncode != 0
    return result


@pytest.fixture
def reg(tmp_path):
    assert CLI.is_file(), "ai-client CLI has not been implemented"
    p = tmp_path / "clients" / "client-tokens.json"
    command(p, "init")
    return p


def token_path(p, name="key"):
    directory = p.parent.parent / "delivery"
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory / name


def test_cli_exists():
    assert CLI.is_file()


def test_create_only_sends_key_to_protected_file(reg):
    out = token_path(reg)
    r = command(reg, "create", "openclaw-test", "--scopes", "gateway,mcp,llm,embeddings", "--token-file", out)
    token = out.read_text().strip()
    assert token.startswith("ai_") and len(token) >= 40
    assert token not in r.stdout + r.stderr + reg.read_text()
    assert stat.S_IMODE(out.stat().st_mode) == 0o400
    assert stat.S_IMODE(reg.stat().st_mode) == 0o400
    assert stat.S_IMODE(reg.parent.stat().st_mode) == 0o700
    assert json.loads(reg.read_text())["clients"][0]["token_sha256"] == hashlib.sha256(token.encode()).hexdigest()
    listing = command(reg, "list")
    assert "openclaw-test" in listing.stdout
    assert "token_sha256" not in listing.stdout


def test_lifecycle_rotation_disable_enable_revoke(reg):
    out = token_path(reg); command(reg, "create", "bot", "--scopes", "gateway,llm", "--token-file", out)
    old = out.read_text().strip()
    command(reg, "disable", "bot"); assert not json.loads(reg.read_text())["clients"][0]["enabled"]
    command(reg, "enable", "bot"); assert json.loads(reg.read_text())["clients"][0]["enabled"]
    next_file = token_path(reg, "rotated")
    command(reg, "rotate", "bot", "--token-file", next_file)
    new = next_file.read_text().strip(); assert new != old
    assert hashlib.sha256(old.encode()).hexdigest() not in reg.read_text()
    command(reg, "set-scopes", "bot", "--scopes", "gateway,embeddings")
    assert json.loads(reg.read_text())["clients"][0]["scopes"] == ["embeddings", "gateway"]
    command(reg, "revoke", "bot")
    row = json.loads(reg.read_text())["clients"][0]
    assert not row["enabled"] and row["revoked_at"]
    command(reg, "enable", "bot", ok=False)
    command(reg, "rotate", "bot", "--token-file", token_path(reg,"forbidden"), ok=False)


def test_existing_output_file_prevents_registry_change(reg):
    out = token_path(reg); out.write_text("do-not-overwrite")
    before = reg.read_bytes()
    command(reg, "create", "bot", "--scopes", "gateway,llm", "--token-file", out, ok=False)
    assert reg.read_bytes() == before and out.read_text() == "do-not-overwrite"


def test_output_symlink_is_rejected_without_changing_registry(reg):
    target = token_path(reg, "existing"); target.write_text("safe")
    link = token_path(reg); link.symlink_to(target); before = reg.read_bytes()
    command(reg, "create", "bot", "--scopes", "gateway,llm", "--token-file", link, ok=False)
    assert target.read_text() == "safe" and reg.read_bytes() == before


def test_key_cannot_be_written_inside_mounted_registry_directory(reg):
    command(reg, "create", "bot", "--scopes", "gateway,llm", "--token-file", reg.parent / "leaky-key", ok=False)
    assert not (reg.parent / "leaky-key").exists()


def test_client_side_digest_enrollment_does_not_require_key_transfer(reg):
    digest = hashlib.sha256(b"test-only-locally-minted-key").hexdigest()
    command(reg, "create", "local-client", "--scopes", "gateway,llm", "--token-sha256", digest)
    assert json.loads(reg.read_text())["clients"][0]["token_sha256"] == digest


def test_unknown_scopes_and_empty_scopes_fail_before_write(reg):
    before = reg.read_bytes()
    for scopes in ("gateway,admin", "mcp,llm", "", "gateway,*"):
        command(reg, "create", "bad", "--scopes", scopes, "--token-file", token_path(reg), ok=False)
    assert reg.read_bytes() == before


def test_migration_preserves_hash_and_disabled_state(tmp_path):
    assert CLI.is_file()
    source = tmp_path / "old.json"
    digest = hashlib.sha256(b"synthetic-legacy-key").hexdigest()
    source.write_text(json.dumps({"version":1, "clients":[{"client_id":"legacy", "token_sha256":digest,"scopes":["gateway","mcp"],"enabled":False}]}))
    p = tmp_path / "clients" / "client-tokens.json"
    command(p, "migrate", "--from-file", source)
    data = json.loads(p.read_text()); row = data["clients"][0]
    assert data["version"] == 2 and row["token_sha256"] == digest and not row["enabled"]
    assert set(row["scopes"]) == {"gateway","mcp","llm","embeddings","reranker","tts","stt","ocr"}
    command(p, "migrate", "--from-file", source, ok=False)


def test_parallel_writers_do_not_lose_clients(reg):
    processes = []
    for i in range(8):
        args = [sys.executable,str(CLI),"--registry",str(reg),"create",f"bot-{i}","--scopes","gateway,llm","--token-file",str(token_path(reg,f"key-{i}"))]
        processes.append(subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True))
    for p in processes:
        _,err = p.communicate(timeout=15); assert p.returncode == 0, err
    assert len(json.loads(reg.read_text())["clients"]) == 8


def test_registry_symlink_cannot_be_administered(reg):
    original = reg.read_bytes(); target = reg.parent / "elsewhere.json"; target.write_bytes(original); reg.unlink(); reg.symlink_to(target)
    command(reg,"create","bad","--scopes","gateway,llm","--token-file",token_path(reg),ok=False)
    assert target.read_bytes() == original


def test_dotdot_cannot_place_plaintext_inside_registry_directory(reg):
    outside = reg.parent.parent / 'other'; outside.mkdir(mode=0o700)
    output = outside / '..' / 'clients' / 'leaked-token'
    before = reg.read_bytes()
    command(reg,'create','bot','--scopes','gateway,llm','--token-file',output,ok=False)
    assert not (reg.parent/'leaked-token').exists() and reg.read_bytes()==before
