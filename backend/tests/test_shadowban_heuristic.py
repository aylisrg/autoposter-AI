"""Tests for shadow-ban visibility heuristic (issue #32)."""
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import HumanizerProfile, Post, PostStatus, PostType, PostVariant, Target
from app.scheduler.jobs import check_shadowbans_tick, leading_shadowban_streak


def test_leading_shadowban_streak() -> None:
    assert leading_shadowban_streak([]) == 0
    assert leading_shadowban_streak([False, True, True]) == 0
    assert leading_shadowban_streak([True, True, False]) == 2
    assert leading_shadowban_streak([True, True, True]) == 3


def test_post_possibly_shadowbanned_default(db: Session) -> None:
    post = Post(
        post_type=PostType.INFORMATIVE,
        status=PostStatus.POSTED,
        text="test post",
        posted_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    assert post.possibly_shadowbanned is False


def test_post_can_be_flagged(db: Session) -> None:
    post = Post(
        post_type=PostType.INFORMATIVE,
        status=PostStatus.POSTED,
        text="test post",
        posted_at=datetime.now(UTC) - timedelta(minutes=10),
        possibly_shadowbanned=True,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    assert post.possibly_shadowbanned is True


def _fb_post(db: Session, *, minutes_ago: int, url: str, flagged: bool = False) -> Post:
    target = Target(platform_id="facebook", external_id=f"https://fb/{url}", name=url)
    db.add(target)
    db.flush()
    post = Post(
        post_type=PostType.INFORMATIVE,
        status=PostStatus.POSTED,
        text="test post",
        posted_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        possibly_shadowbanned=flagged,
    )
    db.add(post)
    db.flush()
    db.add(
        PostVariant(
            post_id=post.id,
            target_id=target.id,
            text="variant",
            status=PostStatus.POSTED,
            external_post_id=f"https://www.facebook.com/{url}",
        )
    )
    db.commit()
    return post


async def test_streak_spans_previous_ticks(db: Session, session_maker, monkeypatch) -> None:
    """Two already-flagged posts plus one new invisible post must pause."""
    from app.scheduler import jobs

    monkeypatch.setattr(jobs, "SessionLocal", session_maker)

    async def invisible(self, url: str):
        return {"visible": False, "reason": "content_not_available"}

    monkeypatch.setattr(
        "app.platforms.facebook.FacebookPlatform.verify_visibility",
        invisible,
    )
    _fb_post(db, minutes_ago=40, url="old-a", flagged=True)
    _fb_post(db, minutes_ago=25, url="old-b", flagged=True)
    fresh = _fb_post(db, minutes_ago=8, url="fresh")

    await check_shadowbans_tick()

    check = session_maker()
    try:
        row = check.get(Post, fresh.id)
        assert row is not None and row.possibly_shadowbanned is True
        profile = check.query(HumanizerProfile).one()
        assert profile.smart_pause_until is not None
        assert "3 consecutive" in (profile.smart_pause_reason or "")
    finally:
        check.close()


async def test_visible_post_breaks_streak(db: Session, session_maker, monkeypatch) -> None:
    from app.scheduler import jobs

    monkeypatch.setattr(jobs, "SessionLocal", session_maker)

    async def visible(self, url: str):
        return {"visible": True, "reason": "article_found"}

    monkeypatch.setattr(
        "app.platforms.facebook.FacebookPlatform.verify_visibility",
        visible,
    )
    _fb_post(db, minutes_ago=40, url="old-a", flagged=True)
    _fb_post(db, minutes_ago=25, url="old-b", flagged=True)
    _fb_post(db, minutes_ago=8, url="fresh")

    await check_shadowbans_tick()

    check = session_maker()
    try:
        assert check.query(HumanizerProfile).first() is None
    finally:
        check.close()


async def test_inconclusive_check_does_not_flag(db: Session, session_maker, monkeypatch) -> None:
    from app.scheduler import jobs

    monkeypatch.setattr(jobs, "SessionLocal", session_maker)

    async def down(self, url: str):
        return None

    monkeypatch.setattr(
        "app.platforms.facebook.FacebookPlatform.verify_visibility",
        down,
    )
    fresh = _fb_post(db, minutes_ago=8, url="fresh")
    await check_shadowbans_tick()

    check = session_maker()
    try:
        row = check.get(Post, fresh.id)
        assert row is not None and row.possibly_shadowbanned is False
        assert check.query(HumanizerProfile).first() is None
    finally:
        check.close()
