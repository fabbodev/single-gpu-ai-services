from hashlib import sha256
from pathlib import Path

import pytest

from auth import HashedTokenVerifier


TEST_TOKEN = "test-bot-token-not-a-real-secret"


@pytest.mark.asyncio
async def test_hashed_token_verifier_accepts_valid_mcp_bot():
    verifier = HashedTokenVerifier.from_file(
        Path(__file__).resolve().parents[2]
        / "tests"
        / "fixtures"
        / "client-tokens.json",
        required_scopes=["mcp"],
    )

    access = await verifier.verify_token(TEST_TOKEN)

    assert access is not None
    assert access.client_id == "test-bot"
    assert "mcp" in access.scopes


@pytest.mark.asyncio
async def test_hashed_token_verifier_rejects_invalid_token():
    verifier = HashedTokenVerifier.from_file(
        Path(__file__).resolve().parents[2]
        / "tests"
        / "fixtures"
        / "client-tokens.json",
        required_scopes=["mcp"],
    )

    assert await verifier.verify_token("wrong-token") is None


def test_config_stores_hash_not_plaintext():
    raw = (
        Path(__file__).resolve().parents[2]
        / "tests"
        / "fixtures"
        / "client-tokens.json"
    ).read_text()

    assert TEST_TOKEN not in raw
    assert sha256(TEST_TOKEN.encode()).hexdigest() in raw


def test_mcp_auth_logger_emits_info_in_production():
    import logging
    import server

    assert server.auth_logger.isEnabledFor(logging.INFO)


def test_mcp_auth_logger_has_runtime_handler():
    import server

    assert server.auth_logger.handlers
