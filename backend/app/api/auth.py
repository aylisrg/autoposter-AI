"""Dashboard PIN auth endpoints.

- POST /api/auth/login { pin } → sets signed cookie
- POST /api/auth/logout        → clears cookie
- GET  /api/auth/status        → { authenticated, auth_required }

Brute-force protection: login attempts are throttled per client IP. See
`_LOGIN_WINDOW_SEC` / `_LOGIN_MAX_ATTEMPTS`. Simple in-memory deque — good
enough for the single-user localhost scope; anything bigger should sit
behind a real reverse proxy with rate-limit.
"""
from __future__ import annotations

import time
from collections import deque
from threading import Lock

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.config import settings
from app.security import (
    _COOKIE_MAX_AGE,
    _COOKIE_NAME,
    _verify_session,
    make_session_cookie,
    verify_pin,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# Rate-limit: 5 failed attempts per 60 s per IP. Successful logins don't count.
_LOGIN_WINDOW_SEC = 60.0
_LOGIN_MAX_ATTEMPTS = 5
_login_failures: dict[str, deque[float]] = {}
_login_lock = Lock()


def _client_ip(request: Request) -> str:
    # Single-user localhost: trust X-Forwarded-For if present (reverse proxy),
    # otherwise fall back to request.client.host. Not spoofing-resistant on its
    # own — that's fine, we just want basic brute-force slowdown.
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_login_rate_limit(request: Request) -> None:
    now = time.monotonic()
    ip = _client_ip(request)
    with _login_lock:
        bucket = _login_failures.setdefault(ip, deque())
        while bucket and now - bucket[0] > _LOGIN_WINDOW_SEC:
            bucket.popleft()
        if len(bucket) >= _LOGIN_MAX_ATTEMPTS:
            retry_after = int(_LOGIN_WINDOW_SEC - (now - bucket[0])) + 1
            raise HTTPException(
                status_code=429,
                detail="Too many login attempts. Slow down.",
                headers={"Retry-After": str(retry_after)},
            )


def _record_login_failure(request: Request) -> None:
    now = time.monotonic()
    ip = _client_ip(request)
    with _login_lock:
        _login_failures.setdefault(ip, deque()).append(now)


class LoginIn(BaseModel):
    pin: str


class AuthStatus(BaseModel):
    auth_required: bool
    authenticated: bool


@router.get("/status", response_model=AuthStatus)
def status(request: Request) -> AuthStatus:
    pin = settings.dashboard_pin.strip()
    if not pin:
        return AuthStatus(auth_required=False, authenticated=True)
    cookie = request.cookies.get(_COOKIE_NAME, "")
    ok = bool(cookie) and _verify_session(cookie, pin)
    return AuthStatus(auth_required=True, authenticated=ok)


@router.post("/login", response_model=AuthStatus)
def login(payload: LoginIn, request: Request, response: Response) -> AuthStatus:
    pin = settings.dashboard_pin.strip()
    if not pin:
        return AuthStatus(auth_required=False, authenticated=True)
    _check_login_rate_limit(request)
    if not verify_pin(payload.pin):
        _record_login_failure(request)
        raise HTTPException(status_code=401, detail="Invalid PIN")
    response.set_cookie(
        key=_COOKIE_NAME,
        value=make_session_cookie(pin),
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return AuthStatus(auth_required=True, authenticated=True)


@router.post("/logout", response_model=AuthStatus)
def logout(response: Response) -> AuthStatus:
    response.delete_cookie(_COOKIE_NAME)
    return AuthStatus(
        auth_required=bool(settings.dashboard_pin.strip()),
        authenticated=False,
    )
