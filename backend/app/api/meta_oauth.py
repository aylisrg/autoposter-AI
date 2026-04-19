"""Meta OAuth endpoints.

Flow for M7:
1. Dashboard hits `GET /api/meta/oauth/url` → we return a login URL (plus the
   `state` nonce the caller must round-trip).
2. User logs in with Facebook, accepts scopes, Meta redirects back to
   `GET /api/meta/oauth/callback?code=...&state=...`.
3. We exchange the code for a short-lived token, upgrade to a long-lived one,
   probe /me/accounts for the IG Business account, and persist two
   PlatformCredential rows (instagram + threads). Threads reuses the same
   long-lived token; the account_id is fetched from settings if present.

Scopes requested (v21.0): `instagram_basic`, `instagram_content_publish`,
`pages_show_list`, `pages_read_engagement`, `threads_basic`,
`threads_content_publish`, `threads_manage_insights`.
"""
from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.db.models import PlatformCredential
from app.platforms import meta_graph
from app.schemas import (
    MetaManualCredentialIn,
    MetaOAuthCompleteOut,
    MetaOAuthUrlOut,
    PlatformCredentialOut,
)

log = logging.getLogger("api.meta_oauth")

router = APIRouter(prefix="/api/meta", tags=["meta"])


META_OAUTH_SCOPES = [
    "instagram_basic",
    "instagram_content_publish",
    "pages_show_list",
    "pages_read_engagement",
    "threads_basic",
    "threads_content_publish",
    "threads_manage_insights",
]
META_LOGIN_URL = "https://www.facebook.com/v21.0/dialog/oauth"


def _upsert_credential(
    db: Session,
    platform_id: str,
    account_id: str,
    access_token: str,
    username: str | None = None,
    extra: dict | None = None,
) -> PlatformCredential:
    """Insert or update a PlatformCredential row by (platform_id, account_id)."""
    row = (
        db.query(PlatformCredential)
        .filter(
            PlatformCredential.platform_id == platform_id,
            PlatformCredential.account_id == account_id,
        )
        .one_or_none()
    )
    if row is None:
        row = PlatformCredential(
            platform_id=platform_id,
            account_id=account_id,
            username=username,
            access_token=access_token,
            extra=extra or {},
        )
        db.add(row)
    else:
        row.access_token = access_token
        if username:
            row.username = username
        if extra is not None:
            row.extra = extra
    db.commit()
    db.refresh(row)
    return row


@router.get("/oauth/url", response_model=MetaOAuthUrlOut)
def oauth_url() -> MetaOAuthUrlOut:
    if not settings.meta_app_id:
        raise HTTPException(
            status_code=400,
            detail="META_APP_ID is not configured in .env",
        )
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": settings.meta_app_id,
        "redirect_uri": settings.meta_redirect_uri,
        "state": state,
        "scope": ",".join(META_OAUTH_SCOPES),
        "response_type": "code",
    }
    return MetaOAuthUrlOut(url=f"{META_LOGIN_URL}?{urlencode(params)}", state=state)


@router.get("/oauth/callback", response_model=MetaOAuthCompleteOut)
def oauth_callback(
    code: str = Query(..., description="Authorization code from Facebook"),
    state: str | None = Query(None),
    db: Session = Depends(get_session),
) -> MetaOAuthCompleteOut:
    """Complete the OAuth dance. Called by Facebook's redirect.

    We deliberately don't verify `state` cryptographically — for a single-user
    localhost tool the CSRF surface is near zero. Any user with a malicious
    redirect would need to trick YOU into authorising their app; out of scope.
    """
    if not settings.meta_app_id or not settings.meta_app_secret:
        raise HTTPException(status_code=400, detail="Meta App credentials missing")

    try:
        short = meta_graph.exchange_code_for_token(
            app_id=settings.meta_app_id,
            app_secret=settings.meta_app_secret,
            redirect_uri=settings.meta_redirect_uri,
            code=code,
        )
        long = meta_graph.long_lived_token(
            app_id=settings.meta_app_id,
            app_secret=settings.meta_app_secret,
            short_token=short["access_token"],
        )
    except meta_graph.MetaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    long_token: str = long["access_token"]

    # Probe pages → pull out the first IG Business account id we find.
    ig_cred: PlatformCredential | None = None
    threads_cred: PlatformCredential | None = None
    try:
        pages = meta_graph.list_pages(long_token)
    except meta_graph.MetaError as exc:
        log.warning("list_pages failed post-OAuth: %s", exc)
        pages = []

    for page in pages:
        ig = page.get("instagram_business_account")
        if not ig:
            continue
        ig_id = ig.get("id")
        if not ig_id:
            continue
        ig_cred = _upsert_credential(
            db,
            platform_id="instagram",
            account_id=ig_id,
            access_token=long_token,
            username=page.get("name"),
            extra={"page_id": page.get("id"), "page_name": page.get("name")},
        )
        break

    # Threads: we don't have a Graph endpoint to enumerate accounts in v1.0,
    # so we fall back to the configured THREADS_USER_ID.
    if settings.threads_user_id:
        threads_cred = _upsert_credential(
            db,
            platform_id="threads",
            account_id=settings.threads_user_id,
            access_token=long_token,
        )

    msg_parts = []
    if ig_cred:
        msg_parts.append(f"Instagram account {ig_cred.account_id} connected")
    if threads_cred:
        msg_parts.append(f"Threads account {threads_cred.account_id} connected")
    if not msg_parts:
        msg_parts.append(
            "Token stored but no IG Business or Threads account was discovered."
        )

    return MetaOAuthCompleteOut(
        instagram=PlatformCredentialOut.model_validate(ig_cred) if ig_cred else None,
        threads=PlatformCredentialOut.model_validate(threads_cred) if threads_cred else None,
        message=". ".join(msg_parts),
    )


@router.post("/credentials", response_model=PlatformCredentialOut)
def add_credential(
    payload: MetaManualCredentialIn,
    db: Session = Depends(get_session),
) -> PlatformCredentialOut:
    """Paste-a-token escape hatch. CLI users who already obtained a long-lived
    token from the Graph API Explorer can wire it in without going through
    the OAuth redirect.
    """
    if payload.platform_id not in {"instagram", "threads"}:
        raise HTTPException(
            status_code=400,
            detail="platform_id must be 'instagram' or 'threads' for this endpoint",
        )
    row = _upsert_credential(
        db,
        platform_id=payload.platform_id,
        account_id=payload.account_id,
        access_token=payload.access_token,
        username=payload.username,
    )
    return PlatformCredentialOut.model_validate(row)
