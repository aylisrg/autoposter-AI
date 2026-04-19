"""Few-shot example store.

We maintain a curated set of top-performing posts per post_type. The Writer
pulls from this store (instead of just thumbs-up posts) so the examples are
based on real engagement, not user opinion.

Refresh policy: keep the top N per post_type ranked by highest PostMetrics
engagement_score across any window. Called by the scheduler weekly; also via
`/api/analyst/generate` as a side-effect.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    FewShotExample,
    Post,
    PostMetrics,
    PostStatus,
    PostType,
    PostVariant,
)


# How many examples to keep per post_type. 3 is plenty — more dilutes voice.
DEFAULT_PER_TYPE = 3


def _best_score_per_post(db: Session) -> dict[int, float]:
    """Max engagement_score across any window for each POSTED post."""
    rows = (
        db.query(
            PostVariant.post_id,
            func.max(PostMetrics.engagement_score),
        )
        .join(PostMetrics, PostMetrics.variant_id == PostVariant.id)
        .group_by(PostVariant.post_id)
        .all()
    )
    return {post_id: float(score or 0.0) for post_id, score in rows}


def refresh_few_shot_store(db: Session, per_type: int = DEFAULT_PER_TYPE) -> int:
    """Recompute and replace the FewShotExample store. Returns rows inserted."""
    scores = _best_score_per_post(db)
    if not scores:
        return 0

    # Fetch posts we have scores for.
    post_ids = list(scores.keys())
    posts: list[Post] = (
        db.query(Post)
        .filter(Post.id.in_(post_ids))
        .filter(Post.status == PostStatus.POSTED)
        .all()
    )
    by_type: dict[PostType, list[tuple[Post, float]]] = defaultdict(list)
    for post in posts:
        by_type[post.post_type].append((post, scores.get(post.id, 0.0)))

    # Nuke old store; a fresh rewrite is simpler and low cost at v1 scale.
    db.query(FewShotExample).delete()
    inserted = 0
    for post_type, items in by_type.items():
        items.sort(key=lambda x: x[1], reverse=True)
        for post, score in items[:per_type]:
            db.add(
                FewShotExample(
                    post_id=post.id,
                    post_type=post_type,
                    text=post.text,
                    engagement_score=score,
                )
            )
            inserted += 1
    db.commit()
    return inserted


def fetch_few_shot_examples(
    db: Session, post_type: PostType, limit: int = 3
) -> list[str]:
    """Pull examples for a given post_type ranked by engagement_score.

    Falls back to an empty list — the Writer simply skips the few-shot prefix.
    """
    rows = (
        db.query(FewShotExample)
        .filter(FewShotExample.post_type == post_type)
        .order_by(FewShotExample.engagement_score.desc())
        .limit(limit)
        .all()
    )
    return [r.text for r in rows]
