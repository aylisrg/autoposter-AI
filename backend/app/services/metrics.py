"""Metrics collection service.

One row per (variant, window). Windows are fixed buckets — 1h, 24h, 7d — so
Analyst comparisons stay apples-to-apples.

A tick is scheduled hourly. For each POSTED variant:
- compute age since `posted_at`
- pick the next un-collected window whose threshold has been crossed
- fetch metrics from the platform and write a PostMetrics row.

Scoring: `engagement_score = likes + 2*comments + 3*shares`. Shares weigh most
because they require effort; comments more than passive likes. Reach is stored
but not yet mixed in — too platform-dependent to normalize naively.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import (
    MetricsWindow,
    PostMetrics,
    PostStatus,
    PostVariant,
    Target,
)
from app.platforms.facebook import FacebookPlatform

log = logging.getLogger("services.metrics")


# How old a variant must be before we collect that window.
WINDOW_THRESHOLDS: dict[MetricsWindow, timedelta] = {
    MetricsWindow.ONE_HOUR: timedelta(hours=1),
    MetricsWindow.ONE_DAY: timedelta(hours=24),
    MetricsWindow.SEVEN_DAY: timedelta(days=7),
}

# After this age we stop polling — a 10-day-old post isn't going to budge
# numbers in a meaningful way and we'd just burn extension cycles.
MAX_AGE = timedelta(days=10)


def compute_engagement_score(
    likes: int, comments: int, shares: int
) -> float:
    return float(likes) + 2.0 * float(comments) + 3.0 * float(shares)


def _platform_for(platform_id: str):
    """Factory. Keep small; real multi-platform dispatch lives in registry."""
    if platform_id == "facebook":
        return FacebookPlatform()
    return None


def _pending_windows(variant: PostVariant, existing: set[MetricsWindow]) -> list[MetricsWindow]:
    if variant.posted_at is None:
        return []
    posted_at = variant.posted_at
    # Normalize to UTC-aware for arithmetic.
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=UTC)
    age = datetime.now(UTC) - posted_at
    if age > MAX_AGE:
        return []
    out = []
    for window, threshold in WINDOW_THRESHOLDS.items():
        if window in existing:
            continue
        if age >= threshold:
            out.append(window)
    return out


async def collect_for_variant(
    db: Session,
    variant: PostVariant,
) -> list[PostMetrics]:
    """Collect any due windows for a single variant. Returns new rows.

    Re-entrant: skips windows already captured. Quiet on platform errors — the
    next tick will retry.
    """
    if variant.status != PostStatus.POSTED or not variant.external_post_id:
        return []
    existing = {
        row.window
        for row in db.query(PostMetrics).filter(PostMetrics.variant_id == variant.id).all()
    }
    windows = _pending_windows(variant, existing)
    if not windows:
        return []

    target = db.get(Target, variant.target_id)
    if target is None:
        return []
    platform = _platform_for(target.platform_id)
    if platform is None:
        log.info(
            "No metrics fetcher for platform %s (variant %s)",
            target.platform_id,
            variant.id,
        )
        return []

    try:
        raw = await platform.fetch_metrics(variant.external_post_id)
    except Exception as exc:
        log.warning("fetch_metrics failed for variant %s: %s", variant.id, exc)
        return []
    if raw is None:
        return []

    likes = int(raw.get("likes") or 0)
    comments = int(raw.get("comments") or 0)
    shares = int(raw.get("shares") or 0)
    reach = raw.get("reach")
    score = compute_engagement_score(likes, comments, shares)
    new_rows: list[PostMetrics] = []
    for window in windows:
        row = PostMetrics(
            variant_id=variant.id,
            window=window,
            likes=likes,
            comments=comments,
            shares=shares,
            reach=reach,
            engagement_score=score,
        )
        db.add(row)
        new_rows.append(row)
    db.commit()
    return new_rows


async def collect_metrics(db: Session) -> dict:
    """Run a full metrics-collection pass. Returns simple counters for logging."""
    candidates: list[PostVariant] = (
        db.query(PostVariant)
        .filter(PostVariant.status == PostStatus.POSTED)
        .filter(PostVariant.external_post_id.is_not(None))
        .all()
    )
    collected = 0
    variants_touched = 0
    for variant in candidates:
        rows = await collect_for_variant(db, variant)
        if rows:
            variants_touched += 1
            collected += len(rows)
    return {"variants_touched": variants_touched, "rows_created": collected}
