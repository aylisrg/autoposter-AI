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

import asyncio
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

    async def publish(self, post: Post, target: Target) -> PublishResult:
        """Send a publish command to the extension."""
        request_id = uuid.uuid4().hex
        payload = {
            "type": "publish",
            "request_id": request_id,
            "target_url": target.external_id,
            "text": post.text,
            "image_url": post.image_url,  # local URL served by backend /static
            "first_comment": post.first_comment,
        }
        try:
            response = await bridge.request(payload, timeout=180)
        except asyncio.TimeoutError:
            return PublishResult(ok=False, error="Extension did not respond in time")

        if response.get("ok"):
            return PublishResult(
                ok=True,
                external_post_id=response.get("post_url") or response.get("post_id"),
                raw=response,
            )
        return PublishResult(
            ok=False,
            error=response.get("error", "Unknown error from extension"),
            raw=response,
        )
