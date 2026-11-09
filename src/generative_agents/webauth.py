"""Optional HTTP Basic authentication for the town and the viewer when they are served to a network.

Both apps are single-user research tools with no accounts. When ``HEARTHSIDE_PASSWORD`` is set
(or ``ga play`` / ``ga serve`` are given a password), every request must carry HTTP Basic
credentials with that password (any user name); browsers prompt once and then send them with
each request. This is a gate for a private deployment behind HTTPS, not a multi-user system:
anyone with the password can do everything the page can do.
"""

from __future__ import annotations

import base64
import hmac
import os
from typing import Any

ENV_VAR = "HEARTHSIDE_PASSWORD"
SPECTATORS_VAR = "HEARTHSIDE_SPECTATORS"  # "1": anyone may watch (GET); the password is needed to act (POST)
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def password_from_env() -> str | None:
    value = os.environ.get(ENV_VAR, "").strip()
    return value or None


def spectators_from_env() -> bool:
    return os.environ.get(SPECTATORS_VAR, "").strip().lower() in ("1", "true", "yes", "on")


def _authorized(header: str | None, password: str) -> bool:
    if not header or not header.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1].strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    _user, sep, given = decoded.partition(":")
    return bool(sep) and hmac.compare_digest(given.encode(), password.encode())


def require_password(app: Any, password: str, realm: str = "Hearthside", *, spectators: bool = False) -> Any:
    """Wrap a FastAPI/Starlette app so requests need the password (HTTP Basic).

    With ``spectators`` on, reads (GET, HEAD, OPTIONS) pass without credentials, so a public
    page can watch the town while chatting, building and controls still need the password.
    """

    from starlette.responses import JSONResponse

    @app.middleware("http")
    async def _gate(request: Any, call_next: Any) -> Any:
        if spectators and request.method in SAFE_METHODS:
            return await call_next(request)
        if _authorized(request.headers.get("authorization"), password):
            return await call_next(request)
        return JSONResponse({"detail": "a password is required"}, status_code=401, headers={"WWW-Authenticate": f'Basic realm="{realm}", charset="UTF-8"'})

    return app
