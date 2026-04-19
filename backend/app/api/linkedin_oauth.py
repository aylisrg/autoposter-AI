"""LinkedIn OAuth endpoints.

Three-legged OIDC flow:
1. Dashboard hits `GET /api/linkedin/oauth/url` → returns the authorization
   URL plus a `state` nonce to round-trip.
2. User signs in at linkedin.com, accepts scopes, LinkedIn redirects back
   to `GET /api/linkedin/oauth/callback?code=...&state=...`.
3. We exchange the code for an access token, pull the OIDC `userinfo` to
   discover the person id, and upsert a PlatformCredential row with
   `platform_id="linkedin"`.

Scopes requested: `openid profile email w_member_social`. `openid`/`profile`
unlock `/v2/userinfo`; `w_member_social` unlocks `/rest/posts` to the
member's own feed.
"""
from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.db.models import PlatformCredential
from app.platforms import linkedin_api
from app.schemas import PlatformCredentialOut
from app.services.audit import audit_event

log = logging.getLogger("api.linkedin_oauth")

router = APIRouter(prefix="/api/linkedin", tags=["linkedin"])


LINKEDIN_SCOPES = ["openid", "profile", "email", "w_member_social"]


class LinkedInOAuthUrlOut(BaseModel):
    url: str
    state: str


class LinkedInOAuthCompleteOut(BaseModel):
    credential: PlatformCredentialOut | None = None
    message: str


class LinkedInManualCredentialIn(BaseModel):
    """Paste-a-token escape hatch. CLI users who already have a valid token
    (e.g. from the LinkedIn API console) can skip the redirect dance.
    """

    account_id: str  # LinkedIn person id (OIDC `sub`).
    access_token: str
    username: str | None = None


def _upsert_credential(
    db: Session,
    *,
    account_id: str,
    access_token: str,
    username: str | None = None,
    extra: dict | None = None,
) -> PlatformCredential:
    row = (
        db.query(PlatformCredential)
        .filter(
            PlatformCredential.platform_id == "linkedin",
            PlatformCredential.account_id == account_id,
        )
        .one_or_none()
    )
    is_new = row is None
    changed: list[str] = []
    if is_new:
        row = PlatformCredential(
            platform_id="linkedin",
            account_id=account_id,
            username=username,
            access_token=access_token,
            extra=extra or {},
        )
        db.add(row)
    else:
        if row.access_token_encrypted != access_token:
            row.access_token = access_token
            changed.append("access_token")
        if username and row.username != username:
            row.username = username
            changed.append("username")
        if extra is not None and row.extra != extra:
            row.extra = extra
            changed.append("extra")
    db.commit()
    db.refresh(row)
    audit_event(
        "created" if is_new else "updated",
        "platform_credential",
        credential_id=row.id,
        platform_id="linkedin",
        account_id=account_id,
        changed_fields=None if is_new else changed,
    )
    return row


@router.get("/oauth/url", response_model=LinkedInOAuthUrlOut)
def oauth_url() -> LinkedInOAuthUrlOut:
    if not settings.linkedin_client_id:
        raise HTTPException(
            status_code=400,
            detail="LINKEDIN_CLIENT_ID is not configured in .env",
        )
    state = secrets.token_urlsafe(24)
    params = {
        "response_type": "code",
        "client_id": settings.linkedin_client_id,
        "redirect_uri": settings.linkedin_redirect_uri,
        "state": state,
        "scope": " ".join(LINKEDIN_SCOPES),
    }
    return LinkedInOAuthUrlOut(
        url=f"{linkedin_api.OAUTH_AUTH_URL}?{urlencode(params)}",
        state=state,
    )


@router.get("/oauth/callback", response_model=LinkedInOAuthCompleteOut)
def oauth_callback(
    code: str = Query(..., description="Authorization code from LinkedIn"),
    state: str | None = Query(None),
    db: Session = Depends(get_session),
) -> LinkedInOAuthCompleteOut:
    """Complete the OAuth dance. Called by LinkedIn's redirect.

    Same state-verification caveat as Meta: single-user localhost tool, no
    real CSRF surface, we trust the redirect.
    """
    if not settings.linkedin_client_id or not settings.linkedin_client_secret:
        raise HTTPException(status_code=400, detail="LinkedIn app credentials missing")
    try:
        token_resp = linkedin_api.exchange_code_for_token(
            client_id=settings.linkedin_client_id,
            client_secret=settings.linkedin_client_secret,
            redirect_uri=settings.linkedin_redirect_uri,
            code=code,
        )
    except linkedin_api.LinkedInError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    access_token = token_resp.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="LinkedIn did not return an access_token")

    try:
        userinfo = linkedin_api.get_userinfo(access_token)
    except linkedin_api.LinkedInError as exc:
        raise HTTPException(status_code=400, detail=f"userinfo failed: {exc}") from exc

    sub = userinfo.get("sub")
    if not sub:
        raise HTTPException(
            status_code=400,
            detail="LinkedIn userinfo missing `sub` — cannot derive person URN",
        )

    row = _upsert_credential(
        db,
        account_id=sub,
        access_token=access_token,
        username=userinfo.get("name"),
        extra={
            "email": userinfo.get("email"),
            "locale": userinfo.get("locale"),
        },
    )
    return LinkedInOAuthCompleteOut(
        credential=PlatformCredentialOut.model_validate(row),
        message=f"LinkedIn account {sub} connected",
    )


@router.post("/credentials", response_model=PlatformCredentialOut)
def add_credential(
    payload: LinkedInManualCredentialIn,
    db: Session = Depends(get_session),
) -> PlatformCredentialOut:
    row = _upsert_credential(
        db,
        account_id=payload.account_id,
        access_token=payload.access_token,
        username=payload.username,
    )
    return PlatformCredentialOut.model_validate(row)
