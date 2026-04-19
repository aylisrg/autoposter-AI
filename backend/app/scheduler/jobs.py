"""Scheduler jobs.

`publish_due_posts` — called every 30 s by APScheduler. For each Post in SCHEDULED
whose `scheduled_for` is past, walk its PostVariants and publish through the
Facebook platform (via the Chrome extension bridge). Sleeps a randomised delay
between variants in the range [min_delay_between_posts_sec, max_delay...]
so that a large batch doesn't hit FB in the same second.

Idempotency: posts are promoted to POSTING before dispatch so a second tick
doesn't grab the same row. Per-day rate limiting uses `max_posts_per_day`.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, date, datetime

from sqlalchemy import func
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import SessionLocal
from app.db.models import Post, PostStatus, PostVariant, Target
from app.platforms.facebook import FacebookPlatform
from app.services import humanizer as hz

log = logging.getLogger("scheduler.jobs")


def _posts_today(db) -> int:
    """Count successfully posted variants whose posted_at is today (UTC)."""
    today = date.today()
    return (
        db.query(func.count(PostVariant.id))
        .filter(PostVariant.status == PostStatus.POSTED)
        .filter(func.date(PostVariant.posted_at) == today)
        .scalar()
        or 0
    )


async def _publish_one(
    post: Post, variant: PostVariant, target: Target, humanizer_config: dict | None = None
) -> None:
    platform = FacebookPlatform()
    synthetic = Post(
        id=post.id,
        post_type=post.post_type,
        status=PostStatus.POSTING,
        text=variant.text,
        image_url=post.image_url,
        first_comment=post.first_comment,
        cta_url=post.cta_url,
    )
    try:
        result = await platform.publish(synthetic, target, humanizer=humanizer_config)
    except Exception as exc:  # noqa: BLE001
        variant.status = PostStatus.FAILED
        variant.error = f"Exception: {exc}"
        return

    if result.ok:
        variant.status = PostStatus.POSTED
        variant.external_post_id = result.external_post_id
        variant.posted_at = datetime.now(UTC)
        variant.error = None
    else:
        variant.status = PostStatus.FAILED
        variant.error = result.error


async def publish_due_posts() -> None:
    """One tick of the scheduler."""
    now = datetime.now(UTC)
    db = SessionLocal()
    try:
        # Smart pause: while active, scheduler is idle.
        pause_until = hz.check_pause(db, now=now)
        if pause_until is not None:
            log.info("Smart pause active until %s — skipping tick", pause_until.isoformat())
            return

        # Blackout: if today is a blackout day, don't post.
        if hz.in_blackout(db, now) is not None:
            log.info("Blackout date matches today — skipping tick")
            return

        due = (
            db.query(Post)
            .options(selectinload(Post.variants))
            .filter(Post.status == PostStatus.SCHEDULED)
            .filter(Post.scheduled_for.isnot(None))
            .filter(Post.scheduled_for <= now)
            .order_by(Post.scheduled_for.asc())
            .all()
        )
        if not due:
            return

        profile = hz.get_or_create_profile(db)
        humanizer_config = hz.humanizer_config_for_extension(profile)

        rate_limit = settings.max_posts_per_day
        posted_today = _posts_today(db)

        for post in due:
            if posted_today >= rate_limit:
                log.info(
                    "Daily rate limit reached (%d/%d) — skipping remaining due posts",
                    posted_today,
                    rate_limit,
                )
                break

            post.status = PostStatus.POSTING
            db.commit()

            pending_variants = [
                v
                for v in post.variants
                if v.status in (PostStatus.SCHEDULED, PostStatus.DRAFT)
            ]

            aborted_due_to_pause = False
            for idx, variant in enumerate(pending_variants):
                if posted_today >= rate_limit:
                    break
                # Re-check pause between each variant — a mid-run checkpoint detection
                # could activate it.
                if hz.check_pause(db) is not None:
                    log.warning("Smart pause triggered mid-run; aborting remaining variants")
                    aborted_due_to_pause = True
                    break

                target = db.get(Target, variant.target_id)
                if target is None:
                    variant.status = PostStatus.FAILED
                    variant.error = "Target vanished."
                    db.commit()
                    continue

                await _publish_one(post, variant, target, humanizer_config=humanizer_config)
                db.commit()
                if variant.status == PostStatus.POSTED:
                    posted_today += 1
                    hz.on_success(db, platform_id="facebook")
                else:
                    hz.on_failure(db, platform_id="facebook", reason=variant.error or "")
                    # on_failure may have activated a pause — next loop iteration
                    # picks that up and aborts.

                if idx < len(pending_variants) - 1:
                    delay = random.randint(
                        settings.min_delay_between_posts_sec,
                        settings.max_delay_between_posts_sec,
                    )
                    log.info("Sleeping %d s before next variant", delay)
                    await asyncio.sleep(delay)

            db.refresh(post)
            fresh_variants = list(post.variants)
            if any(v.status == PostStatus.POSTED for v in fresh_variants):
                post.status = PostStatus.POSTED
                post.posted_at = datetime.now(UTC)
            elif all(
                v.status == PostStatus.FAILED for v in fresh_variants
            ) and not aborted_due_to_pause:
                post.status = PostStatus.FAILED
            else:
                post.status = PostStatus.SCHEDULED  # some variants still pending
            db.commit()
            if aborted_due_to_pause:
                break
    finally:
        db.close()
