"""Instagram platform (via Meta Graph API v21.0).

Publishing flow is two-step:
    1. POST /{ig_user_id}/media        (container creation, returns creation_id)
    2. POST /{ig_user_id}/media_publish (publish the container, returns media id)

Requirements before publishing:
- A PlatformCredential row with `platform_id="instagram"` and a long-lived
  user access token. The `account_id` is the IG Business account numeric id.
- `post.image_url` must be PUBLICLY reachable — Meta fetches it server-side.
  For v1 the user is expected to host it themselves (Cloudinary, ImageKit,
  or an ngrok tunnel over our `/static` mount). Local `file://` or
  `localhost` URLs won't work.

Fetching metrics uses the same access token and the /{media_id}/insights
endpoint.
"""
from __future__ import annotations

import logging
import re
from typing import ClassVar

import httpx
from sqlalchemy.orm import Session

from app.db.models import Post, Target
from app.errors import AuthError, RateLimitError, TransientError, ValidationError
from app.platforms import meta_graph
from app.platforms.base import Platform, PublishResult

log = logging.getLogger("platforms.instagram")


def _failure_from_meta(exc: meta_graph.MetaError) -> PublishResult:
    """Translate a classified MetaError into a PublishResult with the right
    transient/retry_after_sec flags for the scheduler to consume.
    """
    retry_after = getattr(exc, "retry_after", None)
    if isinstance(exc, RateLimitError):
        return PublishResult(
            ok=False,
            error=str(exc),
            transient=True,
            retry_after_sec=retry_after,
        )
    if isinstance(exc, AuthError) or isinstance(exc, ValidationError):
        return PublishResult(ok=False, error=str(exc))
    if isinstance(exc, TransientError):
        return PublishResult(ok=False, error=str(exc), transient=True)
    return PublishResult(ok=False, error=str(exc))


# Instagram has a hard 2200-char caption limit.
IG_CAPTION_MAX = 2200
# And a hashtag cap of 30 per caption.
IG_HASHTAG_MAX = 30


def _get_credential(db: Session):
    """Fetch the single Instagram credential row.

    Deferred import so the module stays importable without the DB loaded.
    """
    from app.db.models import PlatformCredential

    return (
        db.query(PlatformCredential)
        .filter(PlatformCredential.platform_id == "instagram")
        .order_by(PlatformCredential.updated_at.desc())
        .first()
    )


def _trim_hashtags(text: str, max_tags: int = IG_HASHTAG_MAX) -> str:
    """Keep only the first `max_tags` hashtags; strip the rest silently."""
    tags_seen = 0

    def _repl(match: re.Match) -> str:
        nonlocal tags_seen
        tags_seen += 1
        return match.group(0) if tags_seen <= max_tags else ""

    return re.sub(r"#[\w\d_]+", _repl, text)


class InstagramPlatform(Platform):
    id: ClassVar[str] = "instagram"
    name: ClassVar[str] = "Instagram"
    max_length: ClassVar[int | None] = IG_CAPTION_MAX
    supports_images: ClassVar[bool] = True
    supports_first_comment: ClassVar[bool] = True

    def __init__(self, db: Session | None = None) -> None:
        # db is optional at construction — list_targets/publish/fetch_metrics
        # accept a db parameter too for when the caller already has a session.
        self._db = db

    # ------- Content adaptation -------

    def adapt_content(self, text: str) -> str:
        """IG caption tweaks: trim hashtag count, then length-truncate.

        Facebook's editor is fine with 30+ hashtags; IG shadow-bans captions
        that spam them. We cap at 30 and truncate the whole caption at
        2200 chars.
        """
        text = _trim_hashtags(text, IG_HASHTAG_MAX)
        if self.max_length and len(text) > self.max_length:
            text = text[: self.max_length - 1] + "\u2026"  # …
        return text

    # ------- Targets -------

    async def list_targets(self, db: Session | None = None) -> list[dict]:
        """Return a single pseudo-target representing the connected IG Business
        account. IG has no "groups" concept — every publish goes to the account.
        """
        session = db or self._db
        if session is None:
            return []
        cred = _get_credential(session)
        if cred is None:
            return []
        return [
            {
                "external_id": cred.account_id,
                "name": cred.username or f"Instagram ({cred.account_id})",
                "meta": {"source": "meta_oauth"},
            }
        ]

    # ------- Publishing -------

    async def publish(
        self,
        post: Post,
        target: Target,
        humanizer: dict | None = None,
        db: Session | None = None,
    ) -> PublishResult:
        session = db or self._db
        if session is None:
            return PublishResult(ok=False, error="No DB session for Instagram publish")
        cred = _get_credential(session)
        if cred is None:
            return PublishResult(ok=False, error="No Instagram credential configured")
        if not post.image_url or not post.image_url.startswith(("http://", "https://")):
            return PublishResult(
                ok=False,
                error="Instagram requires a publicly-reachable image_url (http/https).",
            )

        caption = self.adapt_content(post.text)
        try:
            creation_id = meta_graph.ig_create_container(
                ig_user_id=target.external_id,
                access_token=cred.access_token,
                image_url=post.image_url,
                caption=caption,
            )
            media_id = meta_graph.ig_publish_container(
                ig_user_id=target.external_id,
                access_token=cred.access_token,
                creation_id=creation_id,
            )
        except meta_graph.MetaError as exc:
            return _failure_from_meta(exc)
        except (httpx.ConnectError, httpx.ReadTimeout) as exc:
            # Network-level blips are always transient.
            return PublishResult(ok=False, error=f"Network: {exc}", transient=True)
        except Exception as exc:
            log.exception("Unexpected IG publish failure")
            return PublishResult(ok=False, error=f"Unexpected: {exc}")

        return PublishResult(
            ok=True,
            external_post_id=media_id,
            raw={"creation_id": creation_id, "media_id": media_id},
        )

    # ------- Metrics -------

    async def fetch_metrics(
        self, external_post_id: str, db: Session | None = None
    ) -> dict | None:
        session = db or self._db
        if session is None:
            return None
        cred = _get_credential(session)
        if cred is None:
            return None
        try:
            return meta_graph.ig_insights(external_post_id, cred.access_token)
        except meta_graph.MetaError as exc:
            log.warning("IG insights failed for %s: %s", external_post_id, exc)
            return None
