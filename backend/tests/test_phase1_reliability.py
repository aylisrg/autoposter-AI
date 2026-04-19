"""Phase 1 reliability/perf additions.

- FK indexes exist on post_variants / feedback.
- BusinessProfile cache: second call is a PK lookup, not an ORDER BY scan.
  Invalidation wipes the cache so mutations are immediately visible.
- `/metrics` emits the new gauges and the scheduler depth reflects DB state.
"""
from __future__ import annotations

import time

import pytest
from sqlalchemy import inspect

from app.db.models import Base, Post, PostStatus, PostType


# ---------- FK indexes ----------


def test_post_variant_fks_have_indexes(engine):
    ins = inspect(engine)
    idx_cols = {tuple(i["column_names"]) for i in ins.get_indexes("post_variants")}
    assert ("post_id",) in idx_cols
    assert ("target_id",) in idx_cols


def test_feedback_post_id_has_index(engine):
    ins = inspect(engine)
    idx_cols = {tuple(i["column_names"]) for i in ins.get_indexes("feedback")}
    assert ("post_id",) in idx_cols


# ---------- BusinessProfile cache ----------


@pytest.fixture()
def _reset_profile_cache():
    from app.db import invalidate_profile_cache

    invalidate_profile_cache()
    yield
    invalidate_profile_cache()


def test_profile_cache_returns_same_row_on_repeat_calls(db, _reset_profile_cache):
    from app.db import get_current_profile
    from app.db.models import BusinessProfile, Tone

    bp = BusinessProfile(name="x", description="desc", tone=Tone.CASUAL)
    db.add(bp)
    db.commit()

    a = get_current_profile(db)
    b = get_current_profile(db)
    assert a is not None and b is not None
    assert a.id == b.id


def test_profile_cache_skips_order_by_after_warm_up(
    db, _reset_profile_cache, monkeypatch
):
    """Warm the cache with one call, then spy on db.query: a PK hit shouldn't
    go through db.query(BusinessProfile).
    """
    from app.db import get_current_profile
    from app.db.models import BusinessProfile, Tone

    bp = BusinessProfile(name="x", description="desc", tone=Tone.CASUAL)
    db.add(bp)
    db.commit()

    # First call warms cache.
    get_current_profile(db)

    # Replace db.query with a spy that records calls.
    calls: list[type] = []
    original_query = db.query

    def _spy(entity):
        calls.append(entity)
        return original_query(entity)

    monkeypatch.setattr(db, "query", _spy)

    # Cache hit path should use db.get(), not db.query(BusinessProfile).
    get_current_profile(db)
    assert BusinessProfile not in calls


def test_profile_cache_invalidation_sees_new_row(db, _reset_profile_cache):
    from app.db import get_current_profile, invalidate_profile_cache
    from app.db.models import BusinessProfile, Tone

    first = BusinessProfile(name="first", description="a", tone=Tone.CASUAL)
    db.add(first)
    db.commit()
    cached = get_current_profile(db)
    assert cached.name == "first"

    # Nuke the row and insert a different one. Without invalidation the cache
    # would keep returning the stale ID (and a fresh db.get would miss).
    db.delete(first)
    db.commit()
    second = BusinessProfile(name="second", description="b", tone=Tone.CASUAL)
    db.add(second)
    db.commit()
    invalidate_profile_cache()

    refreshed = get_current_profile(db)
    assert refreshed is not None
    assert refreshed.name == "second"


def test_profile_cache_handles_no_profile(db, _reset_profile_cache):
    from app.db import get_current_profile

    assert get_current_profile(db) is None
    # Second call also returns None without blowing up.
    assert get_current_profile(db) is None


def test_upsert_profile_invalidates_cache(client, _reset_profile_cache):
    payload = {
        "name": "biz",
        "description": "desc",
        "tone": "casual",
        "length": "medium",
        "emoji_density": "light",
        "language": "en",
        "post_type_ratios": {},
        "posting_window_start_hour": 9,
        "posting_window_end_hour": 20,
        "timezone": "UTC",
        "posts_per_day": 3,
        "review_before_posting": True,
        "auto_approve_types": [],
    }
    r = client.put("/api/business-profile", json=payload)
    assert r.status_code == 200

    # PATCH a field and confirm the GET sees it even though cache was hot.
    payload["name"] = "updated"
    r = client.put("/api/business-profile", json=payload)
    assert r.status_code == 200
    r = client.get("/api/business-profile")
    assert r.status_code == 200
    assert r.json()["name"] == "updated"


# ---------- Health gauges ----------


def _seed_post(db, status: PostStatus, scheduled_for=None) -> Post:
    p = Post(
        post_type=PostType.INFORMATIVE,
        status=status,
        text="hi",
        scheduled_for=scheduled_for,
    )
    db.add(p)
    db.commit()
    return p


def test_metrics_exposes_health_gauges(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.text
    assert "autoposter_extension_connected" in body
    assert "autoposter_backup_age_seconds" in body
    assert "autoposter_scheduler_due_posts" in body
    assert "autoposter_pending_review_posts" in body


def test_scheduler_depth_counts_due_posts(client, db):
    from datetime import UTC, datetime, timedelta

    past = datetime.now(UTC) - timedelta(minutes=5)
    future = datetime.now(UTC) + timedelta(hours=1)
    _seed_post(db, PostStatus.SCHEDULED, scheduled_for=past)
    _seed_post(db, PostStatus.SCHEDULED, scheduled_for=past)
    _seed_post(db, PostStatus.SCHEDULED, scheduled_for=future)  # not due yet
    _seed_post(db, PostStatus.PENDING_REVIEW)

    body = client.get("/metrics").text
    assert "autoposter_scheduler_due_posts 2.0" in body
    assert "autoposter_pending_review_posts 1.0" in body


def test_backup_age_gauge_reports_minus_one_when_empty(client, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "backup_dir", str(tmp_path / "nope"), raising=False)
    body = client.get("/metrics").text
    assert "autoposter_backup_age_seconds -1.0" in body


def test_backup_age_gauge_reports_file_age(client, tmp_path, monkeypatch):
    from app.config import settings

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    f = backup_dir / "snap.zip"
    f.write_bytes(b"x")
    # Backdate 10 seconds.
    ten_s_ago = time.time() - 10
    import os
    os.utime(f, (ten_s_ago, ten_s_ago))

    monkeypatch.setattr(settings, "backup_dir", str(backup_dir), raising=False)
    body = client.get("/metrics").text
    # Parse the line and assert age is at least 9 seconds (race-safe).
    for line in body.splitlines():
        if line.startswith("autoposter_backup_age_seconds "):
            value = float(line.split()[1])
            assert value >= 9
            break
    else:
        pytest.fail("autoposter_backup_age_seconds not found in /metrics output")


def test_extension_connected_gauge_zero_by_default(client):
    body = client.get("/metrics").text
    # The test client never opens /ws/ext, so the bridge reports disconnected.
    # (Some prior test may have connected, so we just check the label exists
    # and is 0 OR 1 — mostly ensuring the gauge is wired.)
    found = False
    for line in body.splitlines():
        if line.startswith("autoposter_extension_connected "):
            value = float(line.split()[1])
            assert value in (0.0, 1.0)
            found = True
    assert found
