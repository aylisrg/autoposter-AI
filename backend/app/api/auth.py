"""Dashboard PIN auth endpoints.

- POST /api/auth/login { pin } → sets signed cookie
- POST /api/auth/logout        → clears cookie
- GET  /api/auth/status        → { authenticated, auth_required }
"""
from __future__ import annotations

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
def login(payload: LoginIn, response: Response) -> AuthStatus:
    pin = settings.dashboard_pin.strip()
    if not pin:
        return AuthStatus(auth_required=False, authenticated=True)
    if not verify_pin(payload.pin):
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
