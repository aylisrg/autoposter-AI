"""A/B split testing for posts.

The natural axis is *targets*: you can't A/B within a single Facebook group
(everyone there sees one post), but you can send arm A to half your groups
and arm B to the other half. This module provides two endpoints:

- POST /api/posts/{id}/ab-split — take N text arms, assign them round-robin
  to the post's pending PostVariants, and stamp each variant with its arm
  label. Only DRAFT / SCHEDULED / PENDING_REVIEW variants are touched —
  already-posted rows are left alone so a late split can't rewrite history.
- GET  /api/posts/{id}/ab-results — group the post's variants by ab_arm,
  aggregate engagement from the best-available PostMetrics window (24h
  preferred, 1h fallback), and surface a winner arm by average engagement.

The feature lives behind a dedicated router rather than bolting onto the
/posts router so it stays easy to remove or feature-flag if hobby-scale
sample sizes turn out not to be useful.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, selectinload

from app.db import get_session
from app.db.models import MetricsWindow, Post, PostMetrics, PostStatus, PostVariant

router = APIRouter(prefix="/api/posts", tags=["posts"])


# ---------- Schemas ----------


class AbArmIn(BaseModel):
    label: str = Field(min_length=1, max_length=50)
    text: str = Field(min_length=1)


class AbSplitRequest(BaseModel):
    arms: list[AbArmIn] = Field(min_length=2)


class AbArmAssignment(BaseModel):
    label: str
    variant_ids: list[int]


class AbSplitResponse(BaseModel):
    post_id: int
    assignments: list[AbArmAssignment]


class AbArmResult(BaseModel):
    label: str
    variant_count: int
    posted_count: int
    likes: int
    comments: int
    shares: int
    avg_engagement: float
    # Which metrics window the aggregate was taken from. Null when we have
    # no data for this arm yet.
    window: MetricsWindow | None = None


class AbResultsResponse(BaseModel):
    post_id: int
    arms: list[AbArmResult]
    # Arm with highest avg_engagement among arms that have posted variants.
    # Null when no arm has been published + measured yet.
    winner: str | None


# ---------- Split ----------


_MUTABLE_STATUSES = {
    PostStatus.DRAFT,
    PostStatus.PENDING_REVIEW,
    PostStatus.SCHEDULED,
}


def _load_post(db: Session, post_id: int) -> Post:
    post = (
        db.query(Post)
        .options(selectinload(Post.variants))
        .filter(Post.id == post_id)
        .first()
    )
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.post("/{post_id}/ab-split", response_model=AbSplitResponse)
def ab_split(
    post_id: int,
    payload: AbSplitRequest,
    db: Session = Depends(get_session),
) -> AbSplitResponse:
    # Dedup arm labels — silent duplicates would make the results endpoint
    # misleading.
    labels = [arm.label for arm in payload.arms]
    if len(set(labels)) != len(labels):
        raise HTTPException(status_code=400, detail="Duplicate arm labels")

    post = _load_post(db, post_id)
    # Deterministic order so re-splitting with the same arms lands the same
    # variants on the same arm.
    mutable = sorted(
        (v for v in post.variants if v.status in _MUTABLE_STATUSES),
        key=lambda v: v.id,
    )
    if not mutable:
        raise HTTPException(
            status_code=409,
            detail="No pending variants to split — all are posted or failed",
        )

    buckets: dict[str, list[int]] = {arm.label: [] for arm in payload.arms}
    for idx, variant in enumerate(mutable):
        arm = payload.arms[idx % len(payload.arms)]
        variant.ab_arm = arm.label
        variant.text = arm.text
        buckets[arm.label].append(variant.id)
    db.commit()

    return AbSplitResponse(
        post_id=post_id,
        assignments=[
            AbArmAssignment(label=label, variant_ids=ids)
            for label, ids in buckets.items()
        ],
    )


# ---------- Results ----------


def _pick_metrics_window(
    metrics_by_variant: dict[int, list[PostMetrics]],
) -> MetricsWindow | None:
    """Across all variants in an arm, pick the most-informative shared
    window. 24h beats 1h beats 7d (freshest meaningful signal for a hobby
    tool that mainly cares about recent posts). Returns None if every
    variant in the arm is pre-measurement.
    """
    order = (MetricsWindow.ONE_DAY, MetricsWindow.ONE_HOUR, MetricsWindow.SEVEN_DAY)
    available = {m.window for rows in metrics_by_variant.values() for m in rows}
    for w in order:
        if w in available:
            return w
    return None


def _aggregate_arm(
    label: str,
    variants: Iterable[PostVariant],
    metrics_by_variant: dict[int, list[PostMetrics]],
) -> AbArmResult:
    variants = list(variants)
    posted = [v for v in variants if v.status == PostStatus.POSTED]
    window = _pick_metrics_window(
        {v.id: metrics_by_variant.get(v.id, []) for v in posted}
    )
    likes = comments = shares = 0
    scores: list[float] = []
    if window is not None:
        for v in posted:
            row = next(
                (m for m in metrics_by_variant.get(v.id, []) if m.window == window),
                None,
            )
            if row is None:
                continue
            likes += row.likes
            comments += row.comments
            shares += row.shares
            scores.append(row.engagement_score)
    avg = sum(scores) / len(scores) if scores else 0.0
    return AbArmResult(
        label=label,
        variant_count=len(variants),
        posted_count=len(posted),
        likes=likes,
        comments=comments,
        shares=shares,
        avg_engagement=avg,
        window=window,
    )


@router.get("/{post_id}/ab-results", response_model=AbResultsResponse)
def ab_results(
    post_id: int,
    db: Session = Depends(get_session),
) -> AbResultsResponse:
    post = _load_post(db, post_id)
    split_variants = [v for v in post.variants if v.ab_arm is not None]
    if not split_variants:
        raise HTTPException(
            status_code=404, detail="Post has no A/B split assigned"
        )

    variant_ids = [v.id for v in split_variants]
    rows = (
        db.query(PostMetrics)
        .filter(PostMetrics.variant_id.in_(variant_ids))
        .all()
    )
    metrics_by_variant: dict[int, list[PostMetrics]] = defaultdict(list)
    for row in rows:
        metrics_by_variant[row.variant_id].append(row)

    by_arm: dict[str, list[PostVariant]] = defaultdict(list)
    for v in split_variants:
        by_arm[v.ab_arm].append(v)

    # Iterate in the original arm-assignment order (sorted label preserves
    # determinism across API reads).
    results = [
        _aggregate_arm(label, by_arm[label], metrics_by_variant)
        for label in sorted(by_arm.keys())
    ]
    measurable = [r for r in results if r.posted_count > 0 and r.window is not None]
    winner = max(measurable, key=lambda r: r.avg_engagement).label if measurable else None

    return AbResultsResponse(post_id=post_id, arms=results, winner=winner)
