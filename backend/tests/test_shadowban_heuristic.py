"""Tests for shadow-ban visibility heuristic (issue #32)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.db.models import Post, PostStatus, PostType


def test_post_possibly_shadowbanned_default(db: Session) -> None:
    post = Post(
        post_type=PostType.INFORMATIVE,
        status=PostStatus.POSTED,
        text="test post",
        posted_at=datetime.now(timezone.utc) - timedelta(minutes=10),
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
        posted_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        possibly_shadowbanned=True,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    assert post.possibly_shadowbanned is True
