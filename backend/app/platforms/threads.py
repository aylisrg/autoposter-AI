"""Threads platform (via Meta Threads API v1.0).

Same two-step container flow as Instagram:
    1. POST /{threads_user_id}/threads         → creation_id
    2. POST /{threads_user_id}/threads_publish → media_id

Unlike IG, Threads supports text-only posts (media_type=TEXT) and posts with
a single image (media_type=IMAGE). Carousels and video (media_type=VIDEO /
CAROUSEL) are deliberately not wired for v1 — we can add them when the user
feature-flag-requests it.

The credential lives in PlatformCredential with platform_id="threads" (one row).
"""
from __future__ import annotations

import logging
import re
from typing import ClassVar

from sqlalchemy.orm import Session

from app.db.models import Post, Target
from app.platforms import meta_graph
from app.platforms.base import Platform, PublishResult

log = logging.getLogger("platforms.threads")


# Threads hard limit is 500 chars.
THREADS_MAX = 500


def _get_credential(db: Session):
    from app.db.models import PlatformCredential

    return (
        db.query(PlatformCredential)
        .filter(PlatformCredential.platform_id == "threads")
        .order_by(PlatformCredential.updated_at.desc())
        .first()
    )


class ThreadsPlatform(Platform):
    id: ClassVar[str] = "threads"
    name: ClassVar[str] = "Threads"
    max_length: ClassVar[int | None] = THREADS_MAX
    supports_images: ClassVar[bool] = True
    supports_first_comment: ClassVar[bool] = False

    def __init__(self, db: Session | None = None) -> None:
        self._db = db

    # ------- Content adaptation -------

    def adapt_content(self, text: str) -> str:
        """Threads truncation. Hashtag handling is lenient on Threads — we
        leave the tags alone and only chop length.
        """
        text = text.strip()
        if self.max_length and len(text) > self.max_length:
            # Try to trim on a word boundary so we don't leave half-words.
            cutoff = self.max_length - 1
            slice_ = text[:cutoff]
            last_space = slice_.rfind(" ")
            if last_space > cutoff - 40:  # only if we don't lose too much
                slice_ = slice_[:last_space]
            text = slice_ + "\u2026"
        # Threads recommends no leading whitespace; the regex below just makes
        # consecutive newlines less aggressive (>2 → 2).
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text

    # ------- Targets -------

    async def list_targets(self, db: Session | None = None) -> list[dict]:
        session = db or self._db
        if session is None:
            return []
        cred = _get_credential(session)
        if cred is None:
            return []
        return [
            {
                "external_id": cred.account_id,
                "name": cred.username or f"Threads ({cred.account_id})",
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
            return PublishResult(ok=False, error="No DB session for Threads publish")
        cred = _get_credential(session)
        if cred is None:
            return PublishResult(ok=False, error="No Threads credential configured")

        text = self.adapt_content(post.text)
        image_url = post.image_url
        if image_url and not image_url.startswith(("http://", "https://")):
            # Threads, like IG, needs a public URL.
            log.info("Dropping non-public image_url for Threads: %s", image_url)
            image_url = None

        try:
            creation_id = meta_graph.threads_create_container(
                threads_user_id=target.external_id,
                access_token=cred.access_token,
                text=text,
                image_url=image_url,
            )
            media_id = meta_graph.threads_publish_container(
                threads_user_id=target.external_id,
                access_token=cred.access_token,
                creation_id=creation_id,
            )
        except meta_graph.MetaError as exc:
            return PublishResult(ok=False, error=str(exc))
        except Exception as exc:
            log.exception("Unexpected Threads publish failure")
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
            return meta_graph.threads_insights(external_post_id, cred.access_token)
        except meta_graph.MetaError as exc:
            log.warning("Threads insights failed for %s: %s", external_post_id, exc)
            return None
