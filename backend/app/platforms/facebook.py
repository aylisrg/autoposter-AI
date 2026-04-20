"""Facebook platform.

Facebook has no public API for posting to Groups you're a member of (since 2018).
So: we use a Chrome extension that runs content scripts on facebook.com, and this
class communicates with it via the WebSocket bridge at ws://localhost:8787/ws/ext.

Target.external_id for Facebook is the group URL, e.g.
  https://www.facebook.com/groups/123456789
or profile:
  https://www.facebook.com/  (posts to own profile timeline)
"""
from __future__ import annotations

import uuid

from app.db.models import Post, Target
from app.platforms.base import Platform, PublishResult
from app.ws.extension_bridge import bridge


class FacebookPlatform(Platform):
    id = "facebook"
    name = "Facebook"
    max_length = 63206  # Facebook's actual post limit
    supports_images = True
    supports_first_comment = True

    async def list_targets(self) -> list[dict]:
        """Ask the extension to enumerate groups the user is a member of."""
        request_id = uuid.uuid4().hex
        response = await bridge.request(
            {"type": "list_groups", "request_id": request_id},
            timeout=60,
        )
        groups = response.get("groups", [])
        return [
            {
                "external_id": g["url"],
                "name": g["name"],
                "member_count": g.get("member_count"),
                "meta": {"role": g.get("role")},  # admin, moderator, member
            }
            for g in groups
        ]

    async def publish(
        self, post: Post, target: Target, humanizer: dict | None = None
    ) -> PublishResult:
        """Send a publish command to the extension."""
        request_id = uuid.uuid4().hex
        payload = {
            "type": "publish",
            "request_id": request_id,
            "target_url": target.external_id,
            "text": post.text,
            "image_url": post.image_url,  # local URL served by backend /static
            "first_comment": post.first_comment,
            "humanizer": humanizer,  # content script uses it to pace typing/mouse
        }
        try:
            response = await bridge.request(payload, timeout=240)
        except TimeoutError:
            # Browser not responding — classic transient: extension might be
            # paused, logged out, or the tab is stuck. Worth a retry.
            return PublishResult(
                ok=False,
                error="Extension did not respond in time",
                transient=True,
            )

        if response.get("ok"):
            return PublishResult(
                ok=True,
                external_post_id=response.get("post_url") or response.get("post_id"),
                raw=response,
            )
        # Extension error strings are opaque — default to transient so a flaky
        # page load or throttle gets another shot. User sees the retry cadence
        # in the UI and can intervene if it persists.
        return PublishResult(
            ok=False,
            error=response.get("error", "Unknown error from extension"),
            raw=response,
            transient=True,
        )

    async def fetch_metrics(self, external_post_id: str) -> dict | None:
        """Ask the extension to scrape likes/comments/shares from a post URL.

        external_post_id is the full permalink we captured during publish. The
        extension opens the page (or reuses an existing tab) and scrapes the
        reaction / comment / share counters.
        """
        if not external_post_id or not external_post_id.startswith("http"):
            return None
        request_id = uuid.uuid4().hex
        try:
            response = await bridge.request(
                {
                    "type": "fetch_metrics",
                    "request_id": request_id,
                    "post_url": external_post_id,
                },
                timeout=60,
            )
        except TimeoutError:
            return None
        if not response.get("ok"):
            return None
        m = response.get("metrics", {})
        return {
            "likes": int(m.get("likes") or 0),
            "comments": int(m.get("comments") or 0),
            "shares": int(m.get("shares") or 0),
            "reach": m.get("reach"),
        }
