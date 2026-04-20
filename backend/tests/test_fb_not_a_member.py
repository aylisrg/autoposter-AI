"""FB 'not a member' error is flagged non-transient so the retry loop
doesn't pointlessly re-queue a variant that'll keep hitting the same wall.

Contrast with a generic content-script error ("composer_editor_did_not_open")
which IS transient — the page may have been slow to render and a retry is
reasonable.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import (
    Post,
    PostStatus,
    PostType,
    Target,
)
from app.platforms.facebook import FacebookPlatform


def _make_post_and_target(db=None):
    t = Target(
        platform_id="facebook",
        external_id="https://facebook.com/groups/123",
        name="Private club",
    )
    db.add(t)
    db.commit()
    p = Post(post_type=PostType.INFORMATIVE, status=PostStatus.SCHEDULED, text="hi")
    db.add(p)
    db.commit()
    return p, t


@pytest.mark.asyncio
async def test_fb_not_a_member_is_permanent(db):
    post, target = _make_post_and_target(db)
    with patch("app.platforms.facebook.bridge") as mock_bridge:
        mock_bridge.request = AsyncMock(
            return_value={
                "ok": False,
                "error": "not_a_group_member: join it first",
            }
        )
        result = await FacebookPlatform().publish(post, target)
    assert result.ok is False
    assert result.transient is False
    assert "not_a_group_member" in result.error


@pytest.mark.asyncio
async def test_fb_checkpoint_is_permanent(db):
    post, target = _make_post_and_target(db)
    with patch("app.platforms.facebook.bridge") as mock_bridge:
        mock_bridge.request = AsyncMock(
            return_value={
                "ok": False,
                "error": 'checkpoint_detected: "please re-enter your password"',
            }
        )
        result = await FacebookPlatform().publish(post, target)
    assert result.ok is False
    assert result.transient is False


@pytest.mark.asyncio
async def test_fb_generic_content_script_error_is_transient(db):
    post, target = _make_post_and_target(db)
    with patch("app.platforms.facebook.bridge") as mock_bridge:
        mock_bridge.request = AsyncMock(
            return_value={
                "ok": False,
                "error": "composer_editor_did_not_open",
            }
        )
        result = await FacebookPlatform().publish(post, target)
    assert result.ok is False
    assert result.transient is True
