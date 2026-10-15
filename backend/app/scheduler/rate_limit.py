"""Per-platform hourly rate limits and per-group cooldowns for the scheduler.

Called from jobs.py before dispatching a variant so we don't flood a platform
or a single Facebook group.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import PostStatus, PostVariant, Target


def posts_in_last_hour(db: Session, platform_id: str, now: datetime | None = None) -> int:
    """How many successfully posted variants for this platform in the last 60 minutes."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=1)
    return (
        db.query(func.count(PostVariant.id))
        .join(Target, PostVariant.target_id == Target.id)
        .filter(Target.platform_id == platform_id)
        .filter(PostVariant.status == PostStatus.POSTED)
        .filter(PostVariant.posted_at.isnot(None))
        .filter(PostVariant.posted_at >= cutoff)
        .scalar()
        or 0
    )


def can_post_to_platform(
    db: Session,
    platform_id: str,
    max_per_hour: int,
    now: datetime | None = None,
) -> bool:
    """True if the platform is under its hourly cap."""
    if max_per_hour <= 0:
        return True
    return posts_in_last_hour(db, platform_id, now) < max_per_hour


def last_posted_at_for_target(db: Session, target_id: int) -> datetime | None:
    """Most recent posted_at for a given target (group), or None."""
    return (
        db.query(func.max(PostVariant.posted_at))
        .filter(PostVariant.target_id == target_id)
        .filter(PostVariant.status == PostStatus.POSTED)
        .filter(PostVariant.posted_at.isnot(None))
        .scalar()
    )


def group_cooldown_ok(
    db: Session,
    target_id: int,
    min_cooldown_sec: int,
    now: datetime | None = None,
) -> bool:
    """True if enough time has passed since the last post to this group."""
    if min_cooldown_sec <= 0:
        return True
    last = last_posted_at_for_target(db, target_id)
    if last is None:
        return True
    now = now or datetime.now(UTC)
    # SQLite may return naive datetimes; normalize.
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return (now - last).total_seconds() >= min_cooldown_sec
