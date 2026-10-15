"""Unit tests for M4 scheduler rate limits and time distribution.

Covers:
- hourly per-platform cap
- per-group cooldown
- jitter distribution (already covered in humanizer, re-asserted here for the DoD)
"""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import Post, PostStatus, PostType, PostVariant, Target
from app.scheduler import rate_limit as rl
from app.services import humanizer as hz


def _make_target(db, platform_id="facebook", external_id="g1", name="Group 1"):
    t = Target(platform_id=platform_id, external_id=external_id, name=name)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _make_post(db):
    p = Post(text="hello", status=PostStatus.SCHEDULED, post_type=PostType.INFORMATIVE)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _make_variant(db, post, target, status=PostStatus.POSTED, posted_at=None):
    v = PostVariant(
        post_id=post.id,
        target_id=target.id,
        text="variant",
        status=status,
        posted_at=posted_at,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def test_hourly_platform_limit(db):
    now = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    t = _make_target(db)
    post = _make_post(db)
    # 5 posts in the last hour
    for i in range(5):
        _make_variant(db, post, t, posted_at=now - timedelta(minutes=10 + i))
    assert rl.posts_in_last_hour(db, "facebook", now) == 5
    assert rl.can_post_to_platform(db, "facebook", max_per_hour=5, now=now) is False
    assert rl.can_post_to_platform(db, "facebook", max_per_hour=6, now=now) is True
    # Old post outside the window does not count
    _make_variant(db, post, t, posted_at=now - timedelta(hours=2))
    assert rl.posts_in_last_hour(db, "facebook", now) == 5


def test_group_cooldown(db):
    now = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    t = _make_target(db)
    post = _make_post(db)
    assert rl.group_cooldown_ok(db, t.id, 1800, now=now) is True  # no prior post
    _make_variant(db, post, t, posted_at=now - timedelta(minutes=10))
    assert rl.group_cooldown_ok(db, t.id, 1800, now=now) is False
    assert rl.group_cooldown_ok(db, t.id, 300, now=now) is True  # 5 min cooldown ok


def test_jitter_distribution(db):
    """Distribution of offsets stays inside ±N minutes (DoD)."""
    from app.db.models import HumanizerProfile

    profile = HumanizerProfile(schedule_jitter_minutes=7)
    db.add(profile)
    db.commit()
    base = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    random.seed(123)
    deltas = []
    for _ in range(100):
        out = hz.apply_schedule_jitter(base, profile)
        deltas.append(abs((out - base).total_seconds()))
    assert all(d <= 7 * 60 + 1 for d in deltas)
    # Roughly uniform-ish: some small, some larger
    assert min(deltas) < 60
    assert max(deltas) > 5 * 60


@pytest.mark.asyncio
async def test_cooldown_defer_keeps_post_scheduled(db, session_maker, monkeypatch):
    """If one variant posts and another is in cooldown, the post stays scheduled."""
    from app.config import settings
    from app.scheduler import jobs

    now = datetime.now(UTC)
    hot = _make_target(db, external_id="hot", name="Hot group")
    cold = _make_target(db, external_id="cold", name="Cold group")
    prior = _make_post(db)
    _make_variant(db, prior, hot, posted_at=now - timedelta(minutes=5))

    post = _make_post(db)
    post.scheduled_for = now - timedelta(minutes=1)
    db.commit()
    hot_variant = _make_variant(db, post, hot, status=PostStatus.SCHEDULED, posted_at=None)
    cold_variant = _make_variant(db, post, cold, status=PostStatus.SCHEDULED, posted_at=None)

    monkeypatch.setattr(jobs, "SessionLocal", session_maker)
    monkeypatch.setattr(settings, "min_delay_between_posts_sec", 0)
    monkeypatch.setattr(settings, "max_delay_between_posts_sec", 0)
    monkeypatch.setattr(settings, "min_group_cooldown_sec", 1800)

    async def fake_publish(post, variant, target, humanizer_config=None, db=None):
        variant.status = PostStatus.POSTED
        variant.posted_at = datetime.now(UTC)

    monkeypatch.setattr(jobs, "_publish_one", fake_publish)

    await jobs.publish_due_posts()

    db.expire_all()
    assert db.get(PostVariant, hot_variant.id).status == PostStatus.SCHEDULED
    assert db.get(PostVariant, cold_variant.id).status == PostStatus.POSTED
    assert db.get(Post, post.id).status == PostStatus.SCHEDULED
