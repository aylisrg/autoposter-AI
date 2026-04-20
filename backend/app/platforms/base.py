"""Platform abstraction for multi-platform posting.

A Platform is one social network: Facebook, LinkedIn, X, Reddit, etc.
Each implementation decides HOW it posts:
- Browser automation via Chrome extension (FB Groups, FB Profile, LinkedIn)
- Official API (X, Bluesky, Telegram, Reddit with OAuth)
- Webhooks / bot APIs (Telegram channels)

Public interface:
- list_targets() — what can I post to? (groups, pages, channels, subreddits, ...)
- publish(post, target) — post this to this target. Returns PublishResult.
- adapt_content(post) — tweak content for platform constraints (length, hashtags).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from app.db.models import Post, Target


@dataclass
class PublishResult:
    ok: bool
    external_post_id: str | None = None
    error: str | None = None
    raw: dict | None = None
    # Retry hints — populated when ok=False. Scheduler consumes these to decide
    # whether to enqueue a retry or mark the variant terminally FAILED.
    # `transient=True` means the error is worth retrying; `retry_after` is the
    # platform's suggested delay in seconds (None = use default backoff).
    transient: bool = False
    retry_after: int | None = None


class Platform(ABC):
    """Abstract platform. Register subclasses in `registry.PLATFORMS`."""

    # Unique key used in DB (Target.platform_id)
    id: ClassVar[str]
    # Human-readable name
    name: ClassVar[str]
    # Max content length (None = no hard limit)
    max_length: ClassVar[int | None] = None
    # Does this platform support images?
    supports_images: ClassVar[bool] = True
    # Does this platform support a "first comment" feature?
    supports_first_comment: ClassVar[bool] = False

    @abstractmethod
    async def list_targets(self) -> list[dict]:
        """Return available targets (groups/pages/subreddits/etc) as dicts.

        Each dict has: external_id, name, and any platform-specific metadata.
        These are meant to be persisted as Target rows.
        """

    @abstractmethod
    async def publish(
        self, post: Post, target: Target, humanizer: dict | None = None
    ) -> PublishResult:
        """Post the given content to the target.

        `humanizer` is a JSON-serializable dict of per-character typing speed,
        mistake rate, mouse curvature, idle-scroll durations, etc. Platforms
        that use a browser (Chrome extension) forward it verbatim to the
        content script; API-based platforms can ignore it.
        """

    async def fetch_metrics(self, external_post_id: str) -> dict | None:
        """Return engagement metrics for a posted item, or None if unsupported.

        Returned dict keys (all optional): `likes`, `comments`, `shares`,
        `reach`. Platforms may return partial data — callers fill the rest
        with zeros / NULL.
        """
        return None

    def adapt_content(self, text: str) -> str:
        """Platform-specific content tweaks.

        Default: truncate to max_length if set. Override for hashtag insertion,
        format stripping, emoji handling, etc.
        """
        if self.max_length and len(text) > self.max_length:
            return text[: self.max_length - 3] + "..."
        return text
