"""Thin wrapper around the Meta Graph + Threads APIs.

Every method is one HTTP call (plus obvious wrappers). Nothing stateful —
the token is passed in. That makes the platforms trivially mockable in
tests.

Endpoints we rely on (v21.0, unchanged for the foreseeable future):

Graph / Instagram publishing (two-step "container" flow):
- POST /{ig_user_id}/media                  → creation_id
- POST /{ig_user_id}/media_publish          → published media id
- GET  /{media_id}/insights                 → reach, impressions, etc.

Graph / OAuth:
- GET  /oauth/access_token                  → exchange code for token
- GET  /me/accounts                         → pages the user manages
- GET  /{page_id}?fields=instagram_business_account

Threads (base URL is `graph.threads.net`, same OAuth scheme):
- POST /{threads_user_id}/threads           → creation_id
- POST /{threads_user_id}/threads_publish   → published media id
- GET  /{media_id}/insights                 → views, likes, replies
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.errors import AuthError, PlatformError, RateLimitError, TransientError, ValidationError

log = logging.getLogger("platforms.meta")


GRAPH_BASE = "https://graph.facebook.com/v21.0"
THREADS_BASE = "https://graph.threads.net/v1.0"


# Meta error codes that indicate rate-limiting / temporary throttling.
# Reference: https://developers.facebook.com/docs/graph-api/overview/rate-limiting
_RATE_LIMIT_CODES = {"4", "17", "32", "613"}

# Meta error codes that mean "credentials are bad — re-auth required."
# 102/190: OAuth/session expired or invalidated. 10/200/299: permission
# errors that typically require re-consent.
_AUTH_CODES = {"10", "102", "190", "200", "299"}

# Codes that mean "the payload is wrong and retrying won't help."
# 100: Invalid parameter. 368: action blocked (usually content policy).
_VALIDATION_CODES = {"100", "368"}


def classify_meta_error(exc: "MetaError") -> PlatformError:
    """Translate a wire-level `MetaError` into the shared hierarchy.

    The scheduler decides retry vs. fail from the class alone, so we collapse
    Meta's hundreds of error codes into four buckets. Anything we don't
    recognise defaults to `TransientError` — better to retry a handful of
    times than silently burn a scheduled post on a transient hiccup we
    didn't catalogue.
    """
    if exc.status == 429 or exc.code in _RATE_LIMIT_CODES:
        return RateLimitError(str(exc), retry_after=exc.retry_after)
    if exc.code in _AUTH_CODES:
        return AuthError(str(exc))
    if exc.code in _VALIDATION_CODES:
        return ValidationError(str(exc))
    if 500 <= exc.status <= 599:
        return TransientError(str(exc))
    # 4xx with an unrecognised code — treat as validation by default. A bad
    # request that isn't rate-limiting or auth almost always means malformed
    # input the user must fix (URL not reachable, image too big, etc).
    if 400 <= exc.status <= 499:
        return ValidationError(str(exc))
    return TransientError(str(exc))


@dataclass
class MetaError(Exception):
    status: int
    code: str
    message: str
    retry_after: int | None = None  # Seconds; None if not rate-limited.

    def __str__(self) -> str:
        suffix = f" (retry after {self.retry_after}s)" if self.retry_after else ""
        return f"[{self.status}/{self.code}] {self.message}{suffix}"


def _parse_retry_after(resp: httpx.Response) -> int | None:
    """Read Retry-After. Meta usually sends seconds; occasionally an HTTP-date
    which we don't bother parsing — treat unparseable as None.
    """
    header = resp.headers.get("retry-after")
    if not header:
        return None
    try:
        return max(0, int(header.strip()))
    except ValueError:
        return None


def _raise_if_error(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        raise MetaError(
            status=resp.status_code,
            code="invalid_json",
            message=resp.text[:200],
            retry_after=_parse_retry_after(resp) if resp.status_code == 429 else None,
        )
    if resp.status_code >= 400 or (isinstance(data, dict) and data.get("error")):
        err = data.get("error") if isinstance(data, dict) else {}
        code = str(err.get("code", "unknown")) if err else "http_error"
        is_rate_limited = resp.status_code == 429 or code in _RATE_LIMIT_CODES
        raise MetaError(
            status=resp.status_code,
            code=code,
            message=(err.get("message") if err else None) or resp.text[:300],
            retry_after=_parse_retry_after(resp) if is_rate_limited else None,
        )
    return data


# ---------- OAuth ----------


def exchange_code_for_token(
    app_id: str, app_secret: str, redirect_uri: str, code: str
) -> dict:
    """Exchange an OAuth code (from the FB redirect) for a short-lived token.

    Returns the JSON as-is. Caller should immediately upgrade to a long-lived
    token via `long_lived_token`.
    """
    with httpx.Client(timeout=30) as c:
        resp = c.get(
            f"{GRAPH_BASE}/oauth/access_token",
            params={
                "client_id": app_id,
                "client_secret": app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
    return _raise_if_error(resp)


def long_lived_token(app_id: str, app_secret: str, short_token: str) -> dict:
    """Exchange a short-lived token (or an existing long-lived one) for a fresh
    ~60-day token. Meta accepts both inputs on the same endpoint — calling
    this with an already-long-lived token is the official refresh path.
    Response: ``{access_token, token_type, expires_in}`` where ``expires_in``
    is seconds (typically ~5_184_000 ≈ 60 days).
    """
    with httpx.Client(timeout=30) as c:
        resp = c.get(
            f"{GRAPH_BASE}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": short_token,
            },
        )
    return _raise_if_error(resp)


def list_pages(access_token: str) -> list[dict]:
    """Return the Facebook Pages the user manages. Each page may have an
    `instagram_business_account` that we need for IG publishing.
    """
    with httpx.Client(timeout=30) as c:
        resp = c.get(
            f"{GRAPH_BASE}/me/accounts",
            params={"access_token": access_token, "fields": "id,name,access_token,instagram_business_account"},
        )
    data = _raise_if_error(resp)
    return data.get("data", [])


# ---------- Instagram publishing ----------


def ig_create_container(
    ig_user_id: str,
    access_token: str,
    image_url: str,
    caption: str,
    is_carousel_item: bool = False,
) -> str:
    payload = {
        "access_token": access_token,
        "image_url": image_url,
        "caption": caption,
    }
    if is_carousel_item:
        payload["is_carousel_item"] = "true"
    with httpx.Client(timeout=60) as c:
        resp = c.post(f"{GRAPH_BASE}/{ig_user_id}/media", data=payload)
    data = _raise_if_error(resp)
    return data["id"]


def ig_publish_container(ig_user_id: str, access_token: str, creation_id: str) -> str:
    with httpx.Client(timeout=60) as c:
        resp = c.post(
            f"{GRAPH_BASE}/{ig_user_id}/media_publish",
            data={"access_token": access_token, "creation_id": creation_id},
        )
    data = _raise_if_error(resp)
    return data["id"]


def ig_insights(media_id: str, access_token: str) -> dict:
    """Minimal insights: we ask for like_count, comments_count, reach, impressions.
    IG returns these as a list of {name, values[{value}]}."""
    with httpx.Client(timeout=30) as c:
        resp = c.get(
            f"{GRAPH_BASE}/{media_id}/insights",
            params={
                "access_token": access_token,
                "metric": "likes,comments,reach,impressions",
            },
        )
    data = _raise_if_error(resp)
    out: dict[str, int | None] = {"likes": 0, "comments": 0, "reach": None}
    for row in data.get("data", []):
        name = row.get("name")
        values = row.get("values") or []
        value = values[0].get("value") if values else None
        if name == "likes":
            out["likes"] = int(value or 0)
        elif name == "comments":
            out["comments"] = int(value or 0)
        elif name == "reach":
            out["reach"] = int(value) if value is not None else None
    return out


# ---------- Threads publishing ----------


def threads_create_container(
    threads_user_id: str,
    access_token: str,
    text: str,
    image_url: str | None = None,
) -> str:
    payload: dict = {
        "access_token": access_token,
        "text": text,
        "media_type": "IMAGE" if image_url else "TEXT",
    }
    if image_url:
        payload["image_url"] = image_url
    with httpx.Client(timeout=60) as c:
        resp = c.post(f"{THREADS_BASE}/{threads_user_id}/threads", data=payload)
    data = _raise_if_error(resp)
    return data["id"]


def threads_publish_container(
    threads_user_id: str, access_token: str, creation_id: str
) -> str:
    with httpx.Client(timeout=60) as c:
        resp = c.post(
            f"{THREADS_BASE}/{threads_user_id}/threads_publish",
            data={"access_token": access_token, "creation_id": creation_id},
        )
    data = _raise_if_error(resp)
    return data["id"]


def get_followers_count(account_id: str, access_token: str, *, is_threads: bool = False) -> int:
    """Current follower count for a Page, IG Business account, or Threads user.

    - FB Page / IG Business → ``followers_count`` via graph.facebook.com.
    - Threads user → ``followers_count`` via graph.threads.net.

    Raises `MetaError` on API failure; we deliberately don't swallow here
    so the scheduler can log and skip, and retries happen at the job level.
    """
    base = THREADS_BASE if is_threads else GRAPH_BASE
    with httpx.Client(timeout=30) as c:
        resp = c.get(
            f"{base}/{account_id}",
            params={"fields": "followers_count", "access_token": access_token},
        )
    data = _raise_if_error(resp)
    # Meta returns the field as a plain int; fall through to 0 if missing so
    # we record a deliberate "we asked, got nothing" rather than crashing.
    return int(data.get("followers_count") or 0)


def threads_insights(media_id: str, access_token: str) -> dict:
    with httpx.Client(timeout=30) as c:
        resp = c.get(
            f"{THREADS_BASE}/{media_id}/insights",
            params={
                "access_token": access_token,
                "metric": "likes,replies,reposts,views",
            },
        )
    data = _raise_if_error(resp)
    out: dict[str, int | None] = {"likes": 0, "comments": 0, "shares": 0, "reach": None}
    for row in data.get("data", []):
        name = row.get("name")
        values = row.get("values") or []
        value = values[0].get("value") if values else None
        if name == "likes":
            out["likes"] = int(value or 0)
        elif name == "replies":
            out["comments"] = int(value or 0)
        elif name == "reposts":
            out["shares"] = int(value or 0)
        elif name == "views":
            out["reach"] = int(value) if value is not None else None
    return out
