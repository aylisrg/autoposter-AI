"""Security helpers — PIN auth + Fernet-at-rest encryption.

## PIN auth
Single-user localhost tool. We ship a single shared PIN (env `DASHBOARD_PIN`,
blank = disabled). Requests to `/api/*` carry the PIN via the
`X-Dashboard-Pin` header OR a signed cookie the dashboard sets after
`POST /api/auth/login`.

The auth surface is deliberately narrow — this is a hobby tool meant to run on
`localhost:8787`. We do NOT claim to be safe on a public interface; if you
expose the dashboard through a tunnel, run it behind nginx + basic auth or a
proper auth proxy.

## Fernet encryption
Long-lived OAuth tokens (`PlatformCredential.access_token`) and API keys
should not be stored as plaintext in the SQLite file. We derive a Fernet key
from `BACKUP_FERNET_KEY` (or a file inside `data/` we generate on first boot)
and expose `encrypt_str` / `decrypt_str` helpers. Backwards-compatible: a
value that fails to decrypt is returned as-is (assumed pre-encryption
plaintext), so existing data keeps working while migration happens
opportunistically on next write.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings

log = logging.getLogger("security")


# ---------- Fernet at rest ----------


_FERNET_KEY_FILE = Path("data/.fernet.key")


def _load_or_create_fernet_key() -> bytes:
    """Priority: settings.fernet_key env → data/.fernet.key file → generate."""
    env_key = settings.fernet_key.strip() if settings.fernet_key else ""
    if env_key:
        return env_key.encode("ascii")
    if _FERNET_KEY_FILE.exists():
        return _FERNET_KEY_FILE.read_bytes().strip()
    _FERNET_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    _FERNET_KEY_FILE.write_bytes(key)
    # tighten perms — only current user can read.
    try:
        os.chmod(_FERNET_KEY_FILE, 0o600)
    except OSError:
        pass
    log.warning(
        "Generated a new Fernet key at %s. Back it up — losing it makes "
        "encrypted values unrecoverable.",
        _FERNET_KEY_FILE,
    )
    return key


_fernet: Fernet | None = None


def fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_fernet_key())
    return _fernet


_FERNET_PREFIX = "fernet:v1:"


def encrypt_str(plain: str) -> str:
    """Encrypt and tag with a prefix so we can distinguish from legacy
    plaintext on read.
    """
    if not plain:
        return plain
    if plain.startswith(_FERNET_PREFIX):
        return plain  # already encrypted
    token = fernet().encrypt(plain.encode("utf-8")).decode("ascii")
    return f"{_FERNET_PREFIX}{token}"


def decrypt_str(value: str) -> str:
    """Decrypt if prefix is present; otherwise return as-is (legacy)."""
    if not value or not value.startswith(_FERNET_PREFIX):
        return value
    token = value[len(_FERNET_PREFIX):]
    try:
        return fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        log.error("Fernet token failed to decrypt — wrong key?")
        return value


# ---------- PIN auth ----------


# Paths that never require the PIN. Keep this tiny.
_PUBLIC_PATHS = {
    "/",
    "/healthz",
    "/api/status",
    "/api/auth/login",
    "/api/auth/status",
    "/api/meta/oauth/callback",  # Meta redirects hit this directly
}

# Path prefixes that bypass auth.
_PUBLIC_PREFIXES = ("/static/", "/ws/")

_COOKIE_NAME = "dashboard_session"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def _hmac_sign(pin: str) -> str:
    """Short opaque session cookie. It's just HMAC(pin) — anyone with the PIN
    can forge it, but they already have the PIN, so that's fine.
    """
    mac = hmac.new(pin.encode("utf-8"), b"dashboard-session", hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")


def _verify_session(cookie_value: str, pin: str) -> bool:
    return hmac.compare_digest(cookie_value, _hmac_sign(pin))


def _is_public(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True
    return any(path.startswith(p) for p in _PUBLIC_PREFIXES)


class DashboardAuthMiddleware(BaseHTTPMiddleware):
    """Blocks /api/* unless the request is authenticated.

    Disabled entirely when `settings.dashboard_pin` is empty (dev default).
    Accepts either an `X-Dashboard-Pin` header matching the configured PIN or
    a valid `dashboard_session` cookie (set by /api/auth/login).
    """

    async def dispatch(self, request: Request, call_next):
        pin = settings.dashboard_pin.strip()
        if not pin:
            return await call_next(request)  # auth disabled
        path = request.url.path
        if _is_public(path) or not path.startswith("/api/"):
            return await call_next(request)
        # CORS preflight needs to go through (OPTIONS gets handled by the CORS
        # middleware which runs first, but some reverse proxies strip it).
        if request.method == "OPTIONS":
            return await call_next(request)

        header = request.headers.get("X-Dashboard-Pin", "")
        if header and hmac.compare_digest(header, pin):
            return await call_next(request)
        cookie = request.cookies.get(_COOKIE_NAME, "")
        if cookie and _verify_session(cookie, pin):
            return await call_next(request)
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )


def make_session_cookie(pin: str) -> str:
    return _hmac_sign(pin)


def verify_pin(candidate: str) -> bool:
    pin = settings.dashboard_pin.strip()
    if not pin:
        return True
    return hmac.compare_digest(candidate or "", pin)


def new_request_id() -> str:
    return secrets.token_hex(8)
