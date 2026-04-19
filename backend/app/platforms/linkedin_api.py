"""Thin wrapper around the LinkedIn REST + OAuth APIs.

Scope of v1: publish text-only and text+image posts to the authenticated
person's feed. Company-page posting is out of scope — the OAuth scopes below
only cover `w_member_social`. Adding `w_organization_social` later is a
one-line scope change.

Endpoints we rely on:

OAuth (3-legged, OIDC flavour):
- GET  https://www.linkedin.com/oauth/v2/authorization  (redirect URL)
- POST https://www.linkedin.com/oauth/v2/accessToken    (code → token)
- GET  https://api.linkedin.com/v2/userinfo             (OIDC `sub` = person id)

Posting (current `/rest/posts` endpoint, versioned header required):
- POST https://api.linkedin.com/rest/posts              → created post URN

The old `/v2/ugcPosts` endpoint still works for legacy apps but LinkedIn
points every new app at `/rest/posts`, so that's what we target.

Every function is a single HTTP call with the token passed in — nothing
stateful, which keeps the platform layer trivially mockable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger("platforms.linkedin")


OAUTH_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
OAUTH_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
API_BASE = "https://api.linkedin.com"
# LinkedIn pins every `/rest/*` endpoint to a monthly version header. We
# target the November 2024 release — posts API hasn't changed meaningfully
# since mid-2023, and LinkedIn promises 12 months of rolling support.
REST_VERSION = "202411"


@dataclass
class LinkedInError(Exception):
    status: int
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.status}/{self.code}] {self.message}"


def _raise_if_error(resp: httpx.Response) -> dict:
    if resp.status_code >= 400:
        try:
            data = resp.json()
        except ValueError:
            data = {}
        raise LinkedInError(
            status=resp.status_code,
            code=str(data.get("serviceErrorCode") or data.get("code") or "http_error"),
            message=data.get("message") or resp.text[:300],
        )
    try:
        return resp.json()
    except ValueError:
        # Some 2xx responses come back empty (e.g. /rest/posts returns the
        # URN in a header, not a body). An empty dict is the right shape.
        return {}


# ---------- OAuth ----------


def exchange_code_for_token(
    *, client_id: str, client_secret: str, redirect_uri: str, code: str
) -> dict:
    """Exchange an authorization code for an access token.

    LinkedIn tokens last 60 days; refresh tokens are 365 days but only issued
    to apps explicitly enrolled in the refresh-token program. For v1 we just
    persist the access token and let the user re-auth when it expires.
    """
    with httpx.Client(timeout=30) as c:
        resp = c.post(
            OAUTH_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    return _raise_if_error(resp)


def get_userinfo(access_token: str) -> dict:
    """OIDC userinfo — returns `sub` (the person id), name, email.

    The `sub` is what we use to build the author URN (`urn:li:person:{sub}`).
    """
    with httpx.Client(timeout=30) as c:
        resp = c.get(
            f"{API_BASE}/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    return _raise_if_error(resp)


# ---------- Publishing ----------


def _build_post_payload(
    *, author_urn: str, text: str, image_urn: str | None
) -> dict:
    """Shape the `/rest/posts` JSON body.

    Keep visibility = PUBLIC and lifecycle = PUBLISHED. The `content` block
    is only present for image posts; plain-text posts omit it entirely.
    """
    body: dict = {
        "author": author_urn,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if image_urn:
        body["content"] = {"media": {"id": image_urn}}
    return body


def create_text_post(
    *, access_token: str, author_urn: str, text: str, image_urn: str | None = None
) -> str:
    """Publish a post. Returns the created post's URN (x-restli-id header)."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "LinkedIn-Version": REST_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }
    with httpx.Client(timeout=60) as c:
        resp = c.post(
            f"{API_BASE}/rest/posts",
            json=_build_post_payload(
                author_urn=author_urn, text=text, image_urn=image_urn
            ),
            headers=headers,
        )
    # LinkedIn returns 201 with the new URN in `x-restli-id` and an empty body.
    if resp.status_code >= 400:
        _raise_if_error(resp)
    urn = resp.headers.get("x-restli-id") or resp.headers.get("X-RestLi-Id")
    if not urn:
        # Fallback — some proxies strip headers. Parse the response body.
        try:
            data = resp.json()
        except ValueError:
            data = {}
        urn = data.get("id") or ""
    if not urn:
        raise LinkedInError(
            status=resp.status_code,
            code="missing_urn",
            message="LinkedIn accepted the post but didn't return a URN",
        )
    return urn


# ---------- Image upload (register + PUT) ----------


def register_image_upload(*, access_token: str, author_urn: str) -> dict:
    """Step 1 of the image upload dance.

    Returns `{uploadUrl, image (URN)}`. The caller PUTs the binary to
    `uploadUrl`, then passes the URN into `create_text_post(image_urn=...)`.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "LinkedIn-Version": REST_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }
    with httpx.Client(timeout=30) as c:
        resp = c.post(
            f"{API_BASE}/rest/images?action=initializeUpload",
            json={"initializeUploadRequest": {"owner": author_urn}},
            headers=headers,
        )
    data = _raise_if_error(resp)
    body = data.get("value") or {}
    upload_url = body.get("uploadUrl")
    image_urn = body.get("image")
    if not upload_url or not image_urn:
        raise LinkedInError(
            status=resp.status_code,
            code="bad_init",
            message="initializeUpload missing uploadUrl/image URN",
        )
    return {"upload_url": upload_url, "image_urn": image_urn}


def upload_image_binary(*, upload_url: str, image_bytes: bytes) -> None:
    """Step 2 — PUT the raw bytes. The upload URL is presigned, no auth header."""
    with httpx.Client(timeout=120) as c:
        resp = c.put(upload_url, content=image_bytes)
    if resp.status_code >= 400:
        raise LinkedInError(
            status=resp.status_code,
            code="upload_failed",
            message=resp.text[:300],
        )
