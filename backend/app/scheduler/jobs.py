"""Scheduler jobs.

`publish_due_posts` — called every 30 s by APScheduler. For each Post in SCHEDULED
whose `scheduled_for` is past, walk its PostVariants and publish through the
Facebook platform (via the Chrome extension bridge). Sleeps a randomised delay
between variants in the range [min_delay_between_posts_sec, max_delay...]
so that a large batch doesn't hit FB in the same second.

Idempotency: posts are promoted to POSTING before dispatch so a second tick
doesn't grab the same row. Per-day rate limiting uses `max_posts_per_day`.

Transient-vs-permanent retry:
- A variant whose publish fails with `result.transient=True` (network, 5xx,
  rate limit) is requeued: `retry_count` bumps, `retry_at` gets set to
  `now + backoff(retry_count)`, and `status` returns to SCHEDULED.
- Permanent failures (auth, validation, unknown error) land at FAILED
  immediately.
- After `MAX_RETRIES` transient attempts we give up and mark FAILED so the
  variant doesn't cycle forever.
- Backoff ladder: 60 s, 300 s, 900 s (total ~20 min). Respects the upstream
  `retry_after_sec` when provided (rate-limit responses).
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import SessionLocal
from app.db.models import Post, PostStatus, PostVariant, Target
from app.platforms.registry import get_platform
from app.services import humanizer as hz
from app.services.rate_limiter import rate_limiter

log = logging.getLogger("scheduler.jobs")


MAX_RETRIES = 3
# Backoff at attempt 1 / 2 / 3 (seconds). After attempt 3 fails, we stop.
_BACKOFF_LADDER = (60, 300, 900)


def _backoff_seconds(retry_count: int, retry_after_hint: int | None) -> int:
    """Pick the wait before the next retry attempt.

    `retry_count` is the count AFTER the failing attempt (>=1). If the
    upstream gave us a Retry-After we honour at least that much.
    """
    idx = min(max(retry_count - 1, 0), len(_BACKOFF_LADDER) - 1)
    ladder = _BACKOFF_LADDER[idx]
    if retry_after_hint is None:
        return ladder
    return max(ladder, retry_after_hint)


def _as_utc(dt: datetime | None) -> datetime | None:
    """SQLite strips timezone on round-trip; re-attach UTC for comparisons."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


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


def _defer_for_retry(
    variant: PostVariant, error: str, retry_after_hint: int | None
) -> None:
    """Transient failure: bump retry_count, set retry_at, keep SCHEDULED so the
    next tick re-picks this variant. Caller is responsible for db.commit().
    """
    variant.retry_count += 1
    wait = _backoff_seconds(variant.retry_count, retry_after_hint)
    variant.retry_at = datetime.now(UTC) + timedelta(seconds=wait)
    variant.status = PostStatus.SCHEDULED
    variant.error = f"[transient #{variant.retry_count}] {error} (retry in {wait}s)"
    log.info(
        "Variant %s transient fail #%d — retry at %s",
        variant.id,
        variant.retry_count,
        variant.retry_at.isoformat(),
    )


def _mark_failed(variant: PostVariant, error: str) -> None:
    variant.status = PostStatus.FAILED
    variant.error = error


async def _publish_one(
    post: Post,
    variant: PostVariant,
    target: Target,
    humanizer_config: dict | None = None,
    db=None,
) -> None:
    platform = get_platform(target.platform_id, db=db)
    if platform is None:
        _mark_failed(variant, f"Unknown platform_id: {target.platform_id}")
        return

    # Client-side rate limit — refuse to dispatch if we'd exceed the per-platform
    # window. Treat a throttle as a transient failure: the variant stays
    # SCHEDULED and retries after `wait` seconds.
    wait = rate_limiter.acquire(target.platform_id)
    if wait is not None:
        if variant.retry_count < MAX_RETRIES:
            _defer_for_retry(variant, "client-side rate limit", retry_after_hint=wait)
        else:
            _mark_failed(variant, "client-side rate limit (max retries exceeded)")
        return

    synthetic = Post(
        id=post.id,
        post_type=post.post_type,
        status=PostStatus.POSTING,
        text=platform.adapt_content(variant.text),
        image_url=post.image_url,
        first_comment=post.first_comment,
        cta_url=post.cta_url,
    )
    try:
        result = await platform.publish(synthetic, target, humanizer=humanizer_config)
    except Exception as exc:  # noqa: BLE001
        # Unknown unhandled exception — treat as non-transient; classified
        # errors come back via PublishResult.transient.
        _mark_failed(variant, f"Exception: {exc}")
        return

    if result.ok:
        variant.status = PostStatus.POSTED
        variant.external_post_id = result.external_post_id
        variant.posted_at = datetime.now(UTC)
        variant.error = None
        variant.retry_at = None  # Clear so it doesn't linger in "waiting" state.
        return

    error_msg = result.error or "Unknown failure"
    if result.transient and variant.retry_count < MAX_RETRIES:
        _defer_for_retry(variant, error_msg, result.retry_after_sec)
    else:
        _mark_failed(
            variant,
            error_msg if not result.transient else f"{error_msg} (max retries exceeded)",
        )


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

            # Only pick variants that are due — skip anything parked by a
            # prior transient failure whose retry_at is still in the future.
            pending_variants = [
                v
                for v in post.variants
                if v.status in (PostStatus.SCHEDULED, PostStatus.DRAFT)
                and (v.retry_at is None or _as_utc(v.retry_at) <= now)
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

                await _publish_one(
                    post, variant, target, humanizer_config=humanizer_config, db=db
                )
                db.commit()
                platform_id = target.platform_id
                if variant.status == PostStatus.POSTED:
                    posted_today += 1
                    hz.on_success(db, platform_id=platform_id)
                else:
                    hz.on_failure(
                        db, platform_id=platform_id, reason=variant.error or ""
                    )
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


# ---------- M6: Metrics + Analyst ticks ----------


async def collect_metrics_tick() -> None:
    """Hourly. Fetch whatever 1h/24h/7d windows are due across all POSTED variants."""
    from app.services import metrics

    db = SessionLocal()
    try:
        result = await metrics.collect_metrics(db)
        if result["rows_created"]:
            log.info(
                "Metrics tick: touched %d variants, created %d rows",
                result["variants_touched"],
                result["rows_created"],
            )
    except Exception:
        log.exception("collect_metrics_tick crashed")
    finally:
        db.close()


async def daily_backup_tick() -> None:
    """Daily zip backup (SQLite + media) to `settings.backup_dir`."""
    from app.services import backups

    try:
        await asyncio.to_thread(backups.run_backup)
    except Exception:
        log.exception("daily_backup_tick crashed")


async def weekly_analyst_tick() -> None:
    """Weekly Analyst run. No-op if profile or fresh metrics are missing."""
    from datetime import timedelta

    from app.agents import analyst
    from app.db import get_current_profile
    from app.db.models import PostMetrics
    from app.services import few_shot

    db = SessionLocal()
    try:
        profile = get_current_profile(db)
        if profile is None:
            log.info("weekly_analyst_tick: no profile, skipping")
            return
        has_metrics = db.query(PostMetrics.id).first() is not None
        if not has_metrics:
            log.info("weekly_analyst_tick: no metrics yet, skipping")
            return
        end = datetime.now(UTC)
        start = end - timedelta(days=7)
        # Heavy Claude call — dispatch to a thread.
        output = await asyncio.to_thread(analyst.run_analysis, db, profile, start, end)
        analyst.persist_report_and_proposals(db, profile, output, start, end)
        few_shot.refresh_few_shot_store(db)
        log.info("weekly_analyst_tick: generated report (cost=$%.4f)", output.cost_usd)
    except Exception:
        log.exception("weekly_analyst_tick crashed")
    finally:
        db.close()
