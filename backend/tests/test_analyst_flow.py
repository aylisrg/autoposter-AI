"""M6 — Metrics + Analyst + Optimizer + Few-shot store.

We mock the platform's `fetch_metrics` and the Anthropic call in the Analyst
agent so tests don't hit external services. Coverage:

- engagement_score formula
- collect_metrics picks the right windows as the variant ages
- MAX_AGE cutoff
- top/bottom performers endpoint
- analyst output → AnalystReport + OptimizerProposal rows
- auto-apply eligible proposals flip the BusinessProfile
- proposal apply/reject endpoints
- few-shot store refresh picks top N per post_type
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.agents import analyst as analyst_agent
from app.db.models import (
    BusinessProfile,
    FewShotExample,
    MetricsWindow,
    OptimizerProposal,
    Post,
    PostMetrics,
    PostStatus,
    PostType,
    PostVariant,
    ProposalStatus,
    Target,
)
from app.services import few_shot, metrics as metrics_service


# ---------- helpers ----------


def _create_profile(db):
    profile = BusinessProfile(
        name="Acme",
        description="We make things.",
        review_before_posting=False,
        posting_window_start_hour=9,
        posting_window_end_hour=20,
        posts_per_day=3,
        post_type_ratios={"informative": 0.5, "hard_sell": 0.3, "engagement": 0.2},
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def _create_target(db, name="Group X"):
    t = Target(
        platform_id="facebook",
        external_id=f"https://www.facebook.com/groups/{name.lower().replace(' ', '')}",
        name=name,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _posted_variant(db, target, post_type=PostType.INFORMATIVE, posted_ago: timedelta = timedelta(hours=2)):
    post = Post(
        post_type=post_type,
        status=PostStatus.POSTED,
        text=f"A post about {post_type.value}.",
        posted_at=datetime.now(UTC) - posted_ago,
    )
    db.add(post)
    db.flush()
    variant = PostVariant(
        post_id=post.id,
        target_id=target.id,
        text=post.text,
        status=PostStatus.POSTED,
        posted_at=post.posted_at,
        external_post_id=f"https://www.facebook.com/groups/fake/posts/{post.id}",
    )
    db.add(variant)
    db.commit()
    db.refresh(variant)
    return post, variant


# ---------- tests ----------


def test_engagement_score_formula():
    assert metrics_service.compute_engagement_score(0, 0, 0) == 0
    assert metrics_service.compute_engagement_score(10, 0, 0) == 10
    assert metrics_service.compute_engagement_score(0, 5, 0) == 10
    assert metrics_service.compute_engagement_score(0, 0, 3) == 9
    assert metrics_service.compute_engagement_score(10, 2, 1) == 17


@pytest.mark.asyncio
async def test_collect_metrics_writes_one_hour_row(db):
    profile = _create_profile(db)  # noqa: F841
    t = _create_target(db)
    _post, variant = _posted_variant(db, t, posted_ago=timedelta(hours=2))

    async def fake_fetch(self, external_post_id):
        return {"likes": 10, "comments": 2, "shares": 1, "reach": None}

    with patch(
        "app.platforms.facebook.FacebookPlatform.fetch_metrics",
        new=fake_fetch,
    ):
        result = await metrics_service.collect_metrics(db)

    assert result["variants_touched"] == 1
    # At 2h old, only the 1h window is due (24h, 7d still pending).
    rows = db.query(PostMetrics).filter(PostMetrics.variant_id == variant.id).all()
    assert len(rows) == 1
    assert rows[0].window == MetricsWindow.ONE_HOUR
    assert rows[0].likes == 10
    assert rows[0].engagement_score == 17  # 10 + 2*2 + 3*1


@pytest.mark.asyncio
async def test_collect_metrics_idempotent(db):
    _create_profile(db)
    t = _create_target(db)
    _, variant = _posted_variant(db, t, posted_ago=timedelta(hours=3))

    async def fake_fetch(self, external_post_id):
        return {"likes": 5, "comments": 1, "shares": 0, "reach": None}

    with patch("app.platforms.facebook.FacebookPlatform.fetch_metrics", new=fake_fetch):
        await metrics_service.collect_metrics(db)
        await metrics_service.collect_metrics(db)  # second call — no new rows

    rows = db.query(PostMetrics).filter(PostMetrics.variant_id == variant.id).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_collect_metrics_respects_max_age(db):
    _create_profile(db)
    t = _create_target(db)
    _, variant = _posted_variant(db, t, posted_ago=timedelta(days=30))

    async def fake_fetch(self, external_post_id):
        return {"likes": 1000}

    with patch("app.platforms.facebook.FacebookPlatform.fetch_metrics", new=fake_fetch):
        result = await metrics_service.collect_metrics(db)

    assert result["rows_created"] == 0
    assert db.query(PostMetrics).count() == 0


@pytest.mark.asyncio
async def test_collect_metrics_multiple_windows_at_8_days(db):
    _create_profile(db)
    t = _create_target(db)
    _, variant = _posted_variant(db, t, posted_ago=timedelta(days=8))

    async def fake_fetch(self, external_post_id):
        return {"likes": 20, "comments": 4, "shares": 2}

    with patch("app.platforms.facebook.FacebookPlatform.fetch_metrics", new=fake_fetch):
        await metrics_service.collect_metrics(db)

    windows = {
        r.window
        for r in db.query(PostMetrics).filter(PostMetrics.variant_id == variant.id).all()
    }
    assert windows == {
        MetricsWindow.ONE_HOUR,
        MetricsWindow.ONE_DAY,
        MetricsWindow.SEVEN_DAY,
    }


def test_analytics_summary_endpoint(client, db):
    _create_profile(db)
    t = _create_target(db)
    _, variant = _posted_variant(db, t, posted_ago=timedelta(hours=2))
    row = PostMetrics(
        variant_id=variant.id,
        window=MetricsWindow.ONE_HOUR,
        likes=50,
        comments=10,
        shares=2,
        engagement_score=76,
    )
    db.add(row)
    db.commit()

    r = client.get("/api/analytics/summary?days=7")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["posts"] == 1
    assert body["likes"] == 50
    assert body["comments"] == 10
    assert body["shares"] == 2
    assert body["avg_engagement_score"] == pytest.approx(76.0)


def test_top_performers_endpoint(client, db):
    _create_profile(db)
    t = _create_target(db)
    # Two posts — one strong, one weak.
    _strong, v_strong = _posted_variant(db, t, posted_ago=timedelta(hours=2))
    _weak, v_weak = _posted_variant(db, t, posted_ago=timedelta(hours=3))

    db.add(
        PostMetrics(
            variant_id=v_strong.id,
            window=MetricsWindow.ONE_HOUR,
            likes=100,
            comments=20,
            shares=5,
            engagement_score=155,
        )
    )
    db.add(
        PostMetrics(
            variant_id=v_weak.id,
            window=MetricsWindow.ONE_HOUR,
            likes=1,
            comments=0,
            shares=0,
            engagement_score=1,
        )
    )
    db.commit()

    r = client.get("/api/analytics/top-performers?limit=2")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["engagement_score"] > body[1]["engagement_score"]

    r_rev = client.get("/api/analytics/top-performers?limit=2&reverse=true")
    assert r_rev.status_code == 200
    assert r_rev.json()[0]["engagement_score"] == 1


def test_analyst_persist_creates_proposals_and_auto_applies(db):
    profile = _create_profile(db)
    period_start = datetime.now(UTC) - timedelta(days=7)
    period_end = datetime.now(UTC)

    output = analyst_agent.AnalystOutput(
        summary="Morning slots outperform evening.",
        body={"summary": "x"},
        proposals=[
            # Eligible for auto-apply (safe field + high confidence)
            analyst_agent.ProposalPayload(
                field="posting_window_start_hour",
                current_value=9,
                proposed_value=10,
                reasoning="Evidence: 3 of 4 top posts posted >= 10am.",
                confidence=0.85,
            ),
            # Not eligible (confidence below threshold)
            analyst_agent.ProposalPayload(
                field="posts_per_day",
                current_value=3,
                proposed_value=4,
                reasoning="Weak signal.",
                confidence=0.5,
            ),
            # Not eligible (tone isn't auto-appliable)
            analyst_agent.ProposalPayload(
                field="tone",
                current_value="casual",
                proposed_value="professional",
                reasoning="Hard-sell underperforms casual.",
                confidence=0.95,
            ),
        ],
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.01,
        model="stub",
    )
    report = analyst_agent.persist_report_and_proposals(
        db, profile, output, period_start, period_end
    )

    proposals = db.query(OptimizerProposal).filter(OptimizerProposal.report_id == report.id).all()
    assert len(proposals) == 3

    by_field = {p.field: p for p in proposals}
    # Auto-applied one
    assert by_field["posting_window_start_hour"].status == ProposalStatus.APPLIED
    assert by_field["posting_window_start_hour"].auto_applied is True
    # Confidence below threshold → pending
    assert by_field["posts_per_day"].status == ProposalStatus.PENDING
    # Tone not in AUTO_APPLIABLE_FIELDS → pending
    assert by_field["tone"].status == ProposalStatus.PENDING

    db.refresh(profile)
    assert profile.posting_window_start_hour == 10
    assert profile.posts_per_day == 3  # Unchanged
    assert profile.tone.value == "casual"  # Unchanged


def test_apply_proposal_endpoint(client, db):
    profile = _create_profile(db)
    p = OptimizerProposal(
        field="posts_per_day",
        current_value={"value": 3},
        proposed_value={"value": 5},
        reasoning="test",
        confidence=0.6,
        status=ProposalStatus.PENDING,
    )
    db.add(p)
    db.commit()
    db.refresh(p)

    r = client.post(f"/api/optimizer/proposals/{p.id}/apply")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "applied"

    db.refresh(profile)
    assert profile.posts_per_day == 5


def test_reject_proposal_endpoint(client, db):
    _create_profile(db)
    p = OptimizerProposal(
        field="tone",
        current_value={"value": "casual"},
        proposed_value={"value": "fun"},
        reasoning="test",
        confidence=0.5,
        status=ProposalStatus.PENDING,
    )
    db.add(p)
    db.commit()

    r = client.post(f"/api/optimizer/proposals/{p.id}/reject")
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


def test_cannot_apply_twice(client, db):
    _create_profile(db)
    p = OptimizerProposal(
        field="posts_per_day",
        current_value={"value": 3},
        proposed_value={"value": 4},
        reasoning="test",
        confidence=0.6,
        status=ProposalStatus.APPLIED,
        applied_at=datetime.now(UTC),
    )
    db.add(p)
    db.commit()
    r = client.post(f"/api/optimizer/proposals/{p.id}/apply")
    assert r.status_code == 409


def test_few_shot_refresh_ranks_and_trims(db):
    _create_profile(db)
    t = _create_target(db)
    # 5 informative posts with escalating scores.
    for i in range(5):
        _, v = _posted_variant(db, t, post_type=PostType.INFORMATIVE, posted_ago=timedelta(hours=2))
        db.add(
            PostMetrics(
                variant_id=v.id,
                window=MetricsWindow.ONE_HOUR,
                likes=i * 10,
                engagement_score=float(i * 10),
            )
        )
    db.commit()

    inserted = few_shot.refresh_few_shot_store(db, per_type=3)
    assert inserted == 3

    stored = (
        db.query(FewShotExample)
        .filter(FewShotExample.post_type == PostType.INFORMATIVE)
        .order_by(FewShotExample.engagement_score.desc())
        .all()
    )
    assert len(stored) == 3
    # Only the top 3 by score.
    assert [s.engagement_score for s in stored] == [40.0, 30.0, 20.0]


def test_analyst_generate_endpoint_with_mock(client, db, monkeypatch):
    _create_profile(db)

    def fake_run_analysis(db_arg, profile, start, end):
        return analyst_agent.AnalystOutput(
            summary="Mocked summary.",
            body={"summary": "Mocked summary.", "proposals": []},
            proposals=[
                analyst_agent.ProposalPayload(
                    field="posting_window_start_hour",
                    current_value=9,
                    proposed_value=10,
                    reasoning="stub",
                    confidence=0.8,
                )
            ],
            input_tokens=10,
            output_tokens=20,
            cost_usd=0.002,
            model="stub-model",
        )

    monkeypatch.setattr(
        "app.api.analytics.analyst_agent.run_analysis",
        fake_run_analysis,
    )
    # Skip few-shot (no posts) — it would return 0 quietly anyway.

    r = client.post("/api/analyst/generate", json={"days": 7})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"] == "Mocked summary."
    assert body["model"] == "stub-model"

    # Proposal was persisted and auto-applied.
    proposals = client.get("/api/optimizer/proposals").json()
    assert len(proposals) == 1
    assert proposals[0]["status"] == "applied"
    assert proposals[0]["auto_applied"] is True
