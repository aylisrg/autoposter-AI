"""LinkedIn platform (via the official REST API, no browser automation).

Scope of v1:
- Person (`urn:li:person:*`) posts. Company pages come later — the OAuth
  scope `w_organization_social` would need to be added.
- Text-only posts and text + single image.
- Reads one PlatformCredential row with `platform_id="linkedin"`. The
  `account_id` is the LinkedIn person id (OIDC `sub`), stored as the raw
  id so we can build the URN at publish time.

Posting flow:
  1. If an `image_url` is attached, fetch the bytes → register upload →
     PUT the bytes → we get back an image URN.
  2. POST /rest/posts with commentary + (optional) image URN.

Metrics: LinkedIn's `socialActions` endpoint gives likes/comments; a full
insights surface needs Marketing-scope tokens we don't ask for. Return
None for now and let the metrics service fill zeros.
"""
from __future__ import annotations

import logging
from typing import ClassVar

import httpx
from sqlalchemy.orm import Session

from app.db.models import Post, Target
from app.platforms import linkedin_api
from app.platforms.base import Platform, PublishResult

log = logging.getLogger("platforms.linkedin")


# LinkedIn's hard cap on commentary is ~3000 chars; we mirror that.
LINKEDIN_MAX = 3000


def _get_credential(db: Session):
    from app.db.models import PlatformCredential

    return (
        db.query(PlatformCredential)
        .filter(PlatformCredential.platform_id == "linkedin")
        .order_by(PlatformCredential.updated_at.desc())
        .first()
    )


def _person_urn(account_id: str) -> str:
    """Build the author URN from the raw person id."""
    if account_id.startswith("urn:li:"):
        return account_id
    return f"urn:li:person:{account_id}"


def _fetch_image_bytes(url: str) -> bytes:
    """Download an image by URL. LinkedIn's `/rest/images` endpoint wants
    the raw binary; we can't pass it a URL like IG does.
    """
    with httpx.Client(timeout=60, follow_redirects=True) as c:
        resp = c.get(url)
    if resp.status_code >= 400:
        raise RuntimeError(f"Could not fetch image {url}: HTTP {resp.status_code}")
    return resp.content


class LinkedInPlatform(Platform):
    id: ClassVar[str] = "linkedin"
    name: ClassVar[str] = "LinkedIn"
    max_length: ClassVar[int | None] = LINKEDIN_MAX
    supports_images: ClassVar[bool] = True
    supports_first_comment: ClassVar[bool] = False

    def __init__(self, db: Session | None = None) -> None:
        self._db = db

    # ------- Content adaptation -------

    def adapt_content(self, text: str) -> str:
        """LinkedIn tolerates hashtags liberally and has a soft 3000-char cap."""
        text = text.strip()
        if self.max_length and len(text) > self.max_length:
            cutoff = self.max_length - 1
            slice_ = text[:cutoff]
            last_space = slice_.rfind(" ")
            if last_space > cutoff - 80:
                slice_ = slice_[:last_space]
            text = slice_ + "\u2026"
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
                "name": cred.username or f"LinkedIn ({cred.account_id})",
                "meta": {"source": "linkedin_oauth"},
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
            return PublishResult(ok=False, error="No DB session for LinkedIn publish")
        cred = _get_credential(session)
        if cred is None:
            return PublishResult(ok=False, error="No LinkedIn credential configured")

        author_urn = _person_urn(target.external_id)
        text = self.adapt_content(post.text)

        image_urn: str | None = None
        if post.image_url and post.image_url.startswith(("http://", "https://")):
            try:
                init = linkedin_api.register_image_upload(
                    access_token=cred.access_token, author_urn=author_urn
                )
                image_bytes = _fetch_image_bytes(post.image_url)
                linkedin_api.upload_image_binary(
                    upload_url=init["upload_url"], image_bytes=image_bytes
                )
                image_urn = init["image_urn"]
            except linkedin_api.LinkedInError as exc:
                classified = linkedin_api.classify_linkedin_error(exc)
                return PublishResult(
                    ok=False,
                    error=f"Image upload failed: {exc}",
                    transient=classified.transient,
                    retry_after=getattr(classified, "retry_after", None),
                )
            except Exception as exc:
                log.exception("Unexpected LinkedIn image upload failure")
                return PublishResult(
                    ok=False, error=f"Image upload: {exc}", transient=True
                )
        elif post.image_url:
            # Non-public URL (localhost / file://) — drop rather than fail so
            # the text still gets out.
            log.info("Dropping non-public image_url for LinkedIn: %s", post.image_url)

        try:
            urn = linkedin_api.create_text_post(
                access_token=cred.access_token,
                author_urn=author_urn,
                text=text,
                image_urn=image_urn,
            )
        except linkedin_api.LinkedInError as exc:
            classified = linkedin_api.classify_linkedin_error(exc)
            return PublishResult(
                ok=False,
                error=str(exc),
                transient=classified.transient,
                retry_after=getattr(classified, "retry_after", None),
            )
        except Exception as exc:
            log.exception("Unexpected LinkedIn publish failure")
            return PublishResult(ok=False, error=f"Unexpected: {exc}", transient=True)

        return PublishResult(
            ok=True,
            external_post_id=urn,
            raw={"post_urn": urn, "image_urn": image_urn},
        )

    # ------- Metrics -------

    async def fetch_metrics(
        self, external_post_id: str, db: Session | None = None
    ) -> dict | None:
        # Full insights need Marketing-scoped tokens. Return None so the
        # metrics service leaves the row alone instead of writing zeros.
        return None
