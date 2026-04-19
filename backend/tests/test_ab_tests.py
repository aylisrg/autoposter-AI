"""Phase 5b — A/B split tests.

Covers:
- Split distributes variants round-robin across arms.
- Arms rewrite variant text and stamp ab_arm.
- Already-posted variants are left alone (so re-splitting can't rewrite
  history of what actually went out).
- Rejects duplicate labels and single-arm splits.
- /ab-results aggregates engagement per arm and picks a winner from the
  freshest shared metrics window.
- Returns 404 if no split has been assigned.
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.db.models import (
    MetricsWindow,
    Post,
    PostMetrics,
    PostStatus,
    PostType,
    PostVariant,
    Target,
)


def _seed(db, *, n_variants: int = 4, all_status: PostStatus = PostStatus.SCHEDULED) -> Post:
    post = Post(post_type=PostType.INFORMATIVE, status=PostStatus.SCHEDULED, text="seed")
    db.add(post)
    db.flush()
    targets = []
    for i in range(n_variants):
        t = Target(
            platform_id="facebook",
            external_id=f"ext-{i}",
            name=f"group {i}",
            tags=[],
            active=True,
            source="manual",
        )
        db.add(t)
        db.flush()
        targets.append(t)
    for t in targets:
        db.add(
            PostVariant(
                post_id=post.id,
                target_id=t.id,
                text=f"original for {t.name}",
                status=all_status,
            )
        )
    db.commit()
    db.refresh(post)
    return post


def _metrics_row(
    variant_id: int,
    window: MetricsWindow,
    likes: int,
    comments: int,
    shares: int,
    engagement: float,
) -> PostMetrics:
    return PostMetrics(
        variant_id=variant_id,
        window=window,
        likes=likes,
        comments=comments,
        shares=shares,
        engagement_score=engagement,
        collected_at=datetime.now(UTC),
    )


# ---------- /ab-split ----------


def test_split_round_robin_assigns_arms(client, db):
    post = _seed(db, n_variants=4)
    r = client.post(
        f"/api/posts/{post.id}/ab-split",
        json={
            "arms": [
                {"label": "a", "text": "arm-a text"},
                {"label": "b", "text": "arm-b text"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    labels = {a["label"]: a["variant_ids"] for a in body["assignments"]}
    assert set(labels) == {"a", "b"}
    assert len(labels["a"]) == 2 and len(labels["b"]) == 2
    # Round-robin in id order: arms receive the 1st and 3rd, 2nd and 4th
    # variants respectively.
    all_ids = sorted(labels["a"] + labels["b"])
    assert labels["a"] == [all_ids[0], all_ids[2]]
    assert labels["b"] == [all_ids[1], all_ids[3]]

    # Variants now carry ab_arm and the arm's text, not the original.
    db.expire_all()
    fresh = db.query(PostVariant).filter(PostVariant.post_id == post.id).all()
    assert all(v.ab_arm in {"a", "b"} for v in fresh)
    assert {v.text for v in fresh if v.ab_arm == "a"} == {"arm-a text"}
    assert {v.text for v in fresh if v.ab_arm == "b"} == {"arm-b text"}


def test_split_leaves_posted_variants_alone(client, db):
    post = _seed(db, n_variants=2, all_status=PostStatus.SCHEDULED)
    # One variant is already POSTED — rewriting its text would be a lie.
    posted_variant = post.variants[0]
    posted_variant.status = PostStatus.POSTED
    db.commit()
    original_text = posted_variant.text

    r = client.post(
        f"/api/posts/{post.id}/ab-split",
        json={
            "arms": [
                {"label": "a", "text": "arm-a text"},
                {"label": "b", "text": "arm-b text"},
            ]
        },
    )
    assert r.status_code == 200

    db.expire_all()
    v0 = db.get(PostVariant, posted_variant.id)
    assert v0.ab_arm is None
    assert v0.text == original_text


def test_split_rejects_duplicate_labels(client, db):
    post = _seed(db, n_variants=2)
    r = client.post(
        f"/api/posts/{post.id}/ab-split",
        json={
            "arms": [
                {"label": "a", "text": "x"},
                {"label": "a", "text": "y"},
            ]
        },
    )
    assert r.status_code == 400


def test_split_requires_at_least_two_arms(client, db):
    post = _seed(db, n_variants=2)
    r = client.post(
        f"/api/posts/{post.id}/ab-split",
        json={"arms": [{"label": "only", "text": "x"}]},
    )
    # Pydantic min_length=2 → 422 validation error.
    assert r.status_code == 422


def test_split_returns_409_when_no_pending_variants(client, db):
    post = _seed(db, n_variants=2, all_status=PostStatus.POSTED)
    r = client.post(
        f"/api/posts/{post.id}/ab-split",
        json={
            "arms": [
                {"label": "a", "text": "x"},
                {"label": "b", "text": "y"},
            ]
        },
    )
    assert r.status_code == 409


def test_split_404_when_post_missing(client):
    r = client.post(
        "/api/posts/999/ab-split",
        json={
            "arms": [
                {"label": "a", "text": "x"},
                {"label": "b", "text": "y"},
            ]
        },
    )
    assert r.status_code == 404


# ---------- /ab-results ----------


def test_ab_results_404_when_not_split(client, db):
    post = _seed(db, n_variants=2)
    r = client.get(f"/api/posts/{post.id}/ab-results")
    assert r.status_code == 404


def test_ab_results_aggregates_per_arm_and_picks_winner(client, db):
    post = _seed(db, n_variants=4)
    variants = sorted(post.variants, key=lambda v: v.id)
    # Assign arms and mark all posted so metrics are measurable.
    for i, v in enumerate(variants):
        v.ab_arm = "a" if i % 2 == 0 else "b"
        v.status = PostStatus.POSTED
        v.text = f"arm-{v.ab_arm}"
    db.commit()

    # Arm A: engagement 1.0 and 2.0 → avg 1.5
    # Arm B: engagement 5.0 and 9.0 → avg 7.0 (winner)
    db.add_all(
        [
            _metrics_row(variants[0].id, MetricsWindow.ONE_DAY, 1, 0, 0, 1.0),
            _metrics_row(variants[1].id, MetricsWindow.ONE_DAY, 5, 0, 0, 5.0),
            _metrics_row(variants[2].id, MetricsWindow.ONE_DAY, 2, 0, 0, 2.0),
            _metrics_row(variants[3].id, MetricsWindow.ONE_DAY, 9, 0, 0, 9.0),
        ]
    )
    db.commit()

    r = client.get(f"/api/posts/{post.id}/ab-results")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["winner"] == "b"
    arms = {a["label"]: a for a in body["arms"]}
    assert arms["a"]["posted_count"] == 2
    assert arms["a"]["likes"] == 3
    assert abs(arms["a"]["avg_engagement"] - 1.5) < 1e-6
    assert arms["b"]["likes"] == 14
    assert abs(arms["b"]["avg_engagement"] - 7.0) < 1e-6
    assert arms["a"]["window"] == "24h"
    assert arms["b"]["window"] == "24h"


def test_ab_results_null_winner_when_no_metrics_yet(client, db):
    post = _seed(db, n_variants=2)
    for v in post.variants:
        v.ab_arm = "a" if v == post.variants[0] else "b"
    db.commit()

    r = client.get(f"/api/posts/{post.id}/ab-results")
    assert r.status_code == 200
    body = r.json()
    assert body["winner"] is None
    for arm in body["arms"]:
        assert arm["posted_count"] == 0
        assert arm["avg_engagement"] == 0.0
        assert arm["window"] is None


def test_ab_results_falls_back_to_1h_when_24h_missing(client, db):
    post = _seed(db, n_variants=2)
    variants = list(post.variants)
    for i, v in enumerate(variants):
        v.ab_arm = "a" if i == 0 else "b"
        v.status = PostStatus.POSTED
    db.commit()

    # Only 1h metrics collected so far.
    db.add_all(
        [
            _metrics_row(variants[0].id, MetricsWindow.ONE_HOUR, 0, 1, 0, 2.0),
            _metrics_row(variants[1].id, MetricsWindow.ONE_HOUR, 0, 2, 0, 4.0),
        ]
    )
    db.commit()

    r = client.get(f"/api/posts/{post.id}/ab-results")
    body = r.json()
    assert body["winner"] == "b"
    for arm in body["arms"]:
        assert arm["window"] == "1h"
