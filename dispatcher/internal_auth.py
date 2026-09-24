import hmac
import os
from pathlib import Path

from fastapi import Header, HTTPException


DEFAULT_TOKEN_FILE = "/run/secrets/dispatcher-token"


def load_internal_token(path=None):
    token_path = path or os.getenv(
        "AI_DISPATCHER_TOKEN_FILE",
        DEFAULT_TOKEN_FILE,
    )
    token = Path(token_path).read_text().strip()
    if len(token) < 32:
        raise ValueError("dispatcher internal token must be at least 32 characters")
    return token


_INTERNAL_TOKEN = load_internal_token()


def require_internal_token(
    x_ai_internal_token: str | None = Header(
        default=None,
        alias="X-AI-Internal-Token",
    ),
):
    if (
        x_ai_internal_token is None
        or not hmac.compare_digest(
            x_ai_internal_token,
            _INTERNAL_TOKEN,
        )
    ):
        raise HTTPException(
            status_code=401,
            detail="invalid internal token",
        )
