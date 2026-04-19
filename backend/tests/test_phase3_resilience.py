"""Phase 3 resilience additions.

- Exception hierarchy: TransientError / RateLimitError / AuthError /
  ValidationError, with Meta subclasses that mix in the tags so callers can
  `except TransientError` across platforms.
- PostVariant gained `retry_count` + `retry_at`; init_db's idempotent
  migration backfills them on older SQLite DBs.
- scheduler._publish_one: transient failures re-queue the variant with an
  exponential backoff; permanent failures go straight to FAILED; retries
  stop after MAX_RETRIES.
- Scheduler tick skips variants whose `retry_at` is still in the future.
- Per-platform RateLimiter blocks inside-window attempts.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import inspect

from app.db.models import Post, PostStatus, PostType, PostVariant, Target
from app.errors import (
    AuthError,
    AutoposterError,
    RateLimitError,
    TransientError,
    ValidationError,
)
from app.platforms import meta_graph
from app.platforms.base import PublishResult


# ---------- Exception hierarchy ----------


def test_meta_rate_limit_is_transient_and_rate_limit():
    exc = meta_graph.MetaRateLimitError(429, "4", "throttled", retry_after=42)
    assert isinstance(exc, TransientError)
    assert isinstance(exc, RateLimitError)
    assert isinstance(exc, meta_graph.MetaError)
    assert isinstance(exc, AutoposterError)
    assert exc.retry_after_sec == 42


def test_meta_auth_is_auth_error():
    exc = meta_graph.MetaAuthError(401, "190", "bad token")
    assert isinstance(exc, AuthError)
    assert isinstance(exc, AutoposterError)
    assert not isinstance(exc, TransientError)


def test_meta_validation_is_validation_error():
    exc = meta_graph.MetaValidationError(400, "100", "bad param")
    assert isinstance(exc, ValidationError)
    assert not isinstance(exc, TransientError)


def test_meta_transient_wraps_5xx():
    exc = meta_graph.MetaTransientError(502, "http_error", "bad gateway")
    assert isinstance(exc, TransientError)


def _make_response(status: int, body: dict, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers or {})


def test_raise_if_error_classifies_rate_limit():
    resp = _make_response(429, {"error": {"code": 4, "message": "throttled"}}, {"retry-after": "30"})
    with pytest.raises(meta_graph.MetaRateLimitError) as ei:
        meta_graph._raise_if_error(resp)
    assert ei.value.retry_after == 30


def test_raise_if_error_classifies_auth():
    resp = _make_response(401, {"error": {"code": 190, "message": "invalid token"}})
    with pytest.raises(meta_graph.MetaAuthError):
        meta_graph._raise_if_error(resp)


def test_raise_if_error_classifies_validation():
    resp = _make_response(400, {"error": {"code": 100, "message": "bad param"}})
    with pytest.raises(meta_graph.MetaValidationError):
        meta_graph._raise_if_error(resp)


def test_raise_if_error_classifies_5xx_as_transient():
    resp = _make_response(503, {"error": {"code": "9999", "message": "overloaded"}})
    with pytest.raises(meta_graph.MetaTransientError):
        meta_graph._raise_if_error(resp)


# ---------- PostVariant retry columns ----------


def test_post_variant_has_retry_columns(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("post_variants")}
    assert "retry_count" in cols
    assert "retry_at" in cols


def test_ensure_retry_columns_is_idempotent(engine):
    """Run the migration helper twice on a live DB — second call is a no-op."""
    from app.db import session as db_session

    with patch.object(db_session, "engine", engine):
        db_session._ensure_post_variant_retry_columns()
        db_session._ensure_post_variant_retry_columns()  # idempotent

    cols = {c["name"] for c in inspect(engine).get_columns("post_variants")}
    assert "retry_count" in cols
    assert "retry_at" in cols


# ---------- Rate limiter ----------


def test_rate_limiter_allows_within_window():
    from app.services.rate_limiter import RateLimiter

    rl = RateLimiter({"x": (3, 60)})
    assert rl.acquire("x", now=0.0) is None
    assert rl.acquire("x", now=1.0) is None
    assert rl.acquire("x", now=2.0) is None


def test_rate_limiter_blocks_past_window():
    from app.services.rate_limiter import RateLimiter

    rl = RateLimiter({"x": (2, 60)})
    assert rl.acquire("x", now=0.0) is None
    assert rl.acquire("x", now=1.0) is None
    # Third call inside 60s must wait.
    wait = rl.acquire("x", now=2.0)
    assert wait is not None
    assert wait > 0


def test_rate_limiter_clears_after_window():
    from app.services.rate_limiter import RateLimiter

    rl = RateLimiter({"x": (1, 60)})
    rl.acquire("x", now=0.0)
    # 61 seconds later the old call has aged out.
    assert rl.acquire("x", now=61.0) is None


def test_rate_limiter_no_limit_means_always_ok():
    from app.services.rate_limiter import RateLimiter

    rl = RateLimiter({})
    for i in range(100):
        assert rl.acquire("unknown", now=float(i)) is None


# ---------- Scheduler retry logic ----------


def _seed_post_with_variant(db) -> tuple[Post, PostVariant, Target]:
    t = Target(platform_id="instagram", name="biz", external_id="acc-1")
    db.add(t)
    db.commit()
    p = Post(
        post_type=PostType.INFORMATIVE,
        status=PostStatus.SCHEDULED,
        text="hello",
        scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
    )
    db.add(p)
    db.commit()
    v = PostVariant(post_id=p.id, target_id=t.id, text="hello there", status=PostStatus.SCHEDULED)
    db.add(v)
    db.commit()
    return p, v, t


class _StubPlatform:
    """Stands in for a real platform.publish; returns what the test dictates."""

    def __init__(self, result: PublishResult) -> None:
        self._result = result

    def adapt_content(self, text: str) -> str:
        return text

    async def publish(self, *_args, **_kwargs) -> PublishResult:
        return self._result


def _mock_get_platform(result: PublishResult):
    return lambda platform_id, db=None: _StubPlatform(result)


def test_transient_failure_defers_variant(db, monkeypatch):
    from app.scheduler import jobs

    p, v, t = _seed_post_with_variant(db)
    monkeypatch.setattr(
        jobs,
        "get_platform",
        _mock_get_platform(PublishResult(ok=False, error="rate limit", transient=True, retry_after_sec=45)),
    )
    # Defeat the per-platform rate limiter so we test the result branch only.
    monkeypatch.setattr(jobs.rate_limiter, "acquire", lambda *_a, **_kw: None)

    asyncio.run(jobs._publish_one(p, v, t, db=db))

    assert v.status == PostStatus.SCHEDULED
    assert v.retry_count == 1
    assert v.retry_at is not None
    assert v.retry_at > datetime.now(UTC)
    assert "transient" in (v.error or "").lower()


def test_permanent_failure_marks_failed_immediately(db, monkeypatch):
    from app.scheduler import jobs

    p, v, t = _seed_post_with_variant(db)
    monkeypatch.setattr(
        jobs,
        "get_platform",
        _mock_get_platform(PublishResult(ok=False, error="invalid token", transient=False)),
    )
    monkeypatch.setattr(jobs.rate_limiter, "acquire", lambda *_a, **_kw: None)

    asyncio.run(jobs._publish_one(p, v, t, db=db))

    assert v.status == PostStatus.FAILED
    assert v.retry_count == 0  # Never got bumped.
    assert v.retry_at is None
    assert "invalid token" in (v.error or "")


def test_max_retries_exceeded_marks_failed(db, monkeypatch):
    from app.scheduler import jobs

    p, v, t = _seed_post_with_variant(db)
    v.retry_count = jobs.MAX_RETRIES  # At the cap already.
    db.commit()
    monkeypatch.setattr(
        jobs,
        "get_platform",
        _mock_get_platform(PublishResult(ok=False, error="still 503", transient=True)),
    )
    monkeypatch.setattr(jobs.rate_limiter, "acquire", lambda *_a, **_kw: None)

    asyncio.run(jobs._publish_one(p, v, t, db=db))
    assert v.status == PostStatus.FAILED
    assert "max retries" in (v.error or "").lower()


def test_client_side_rate_limit_defers_variant(db, monkeypatch):
    from app.scheduler import jobs

    p, v, t = _seed_post_with_variant(db)
    # get_platform should never be called — rate limiter short-circuits.
    called = {"publish": False}

    class _NeverPublish:
        def adapt_content(self, t):
            return t

        async def publish(self, *a, **kw):  # pragma: no cover
            called["publish"] = True
            return PublishResult(ok=True)

    monkeypatch.setattr(jobs, "get_platform", lambda *_a, **_kw: _NeverPublish())
    monkeypatch.setattr(jobs.rate_limiter, "acquire", lambda *_a, **_kw: 120)

    asyncio.run(jobs._publish_one(p, v, t, db=db))

    assert called["publish"] is False
    assert v.status == PostStatus.SCHEDULED
    assert v.retry_count == 1
    assert v.retry_at is not None


def test_success_clears_retry_state(db, monkeypatch):
    from app.scheduler import jobs

    p, v, t = _seed_post_with_variant(db)
    v.retry_count = 1
    v.retry_at = datetime.now(UTC) + timedelta(seconds=120)
    db.commit()
    monkeypatch.setattr(
        jobs,
        "get_platform",
        _mock_get_platform(PublishResult(ok=True, external_post_id="ext-99")),
    )
    monkeypatch.setattr(jobs.rate_limiter, "acquire", lambda *_a, **_kw: None)

    asyncio.run(jobs._publish_one(p, v, t, db=db))

    assert v.status == PostStatus.POSTED
    assert v.external_post_id == "ext-99"
    assert v.retry_at is None
    assert v.error is None


def test_backoff_honors_upstream_retry_after():
    from app.scheduler.jobs import _backoff_seconds

    # Upstream said 500 s; our attempt-1 ladder says 60 s. Use the larger.
    assert _backoff_seconds(1, 500) == 500
    # Our ladder wins if upstream didn't say.
    assert _backoff_seconds(1, None) == 60
    assert _backoff_seconds(2, None) == 300
    assert _backoff_seconds(3, None) == 900


# ---------- Scheduler tick respects retry_at ----------


@pytest.fixture()
def _patch_humanizer(monkeypatch):
    """humanizer helpers hit the DB; neutralise them for scheduler tests."""
    from app.services import humanizer as hz

    monkeypatch.setattr(hz, "check_pause", lambda *_a, **_kw: None)
    monkeypatch.setattr(hz, "in_blackout", lambda *_a, **_kw: None)
    monkeypatch.setattr(hz, "get_or_create_profile", lambda _db: None)
    monkeypatch.setattr(hz, "humanizer_config_for_extension", lambda _p: None)
    monkeypatch.setattr(hz, "on_success", lambda *_a, **_kw: None)
    monkeypatch.setattr(hz, "on_failure", lambda *_a, **_kw: None)


def test_tick_skips_variant_whose_retry_at_is_future(db, session_maker, monkeypatch, _patch_humanizer):
    from app.db import session as db_session
    from app.scheduler import jobs

    monkeypatch.setattr(db_session, "SessionLocal", session_maker, raising=True)
    monkeypatch.setattr(jobs, "SessionLocal", session_maker, raising=True)
    # Rate limiter out of the way.
    monkeypatch.setattr(jobs.rate_limiter, "acquire", lambda *_a, **_kw: None)

    p, v, t = _seed_post_with_variant(db)
    v.retry_count = 1
    v.retry_at = datetime.now(UTC) + timedelta(hours=1)
    db.commit()

    # Stub get_platform so IF it gets called the test fails loudly.
    called = {"n": 0}

    class _Fail:
        def adapt_content(self, t):
            return t

        async def publish(self, *a, **kw):  # pragma: no cover
            called["n"] += 1
            return PublishResult(ok=True)

    monkeypatch.setattr(jobs, "get_platform", lambda *_a, **_kw: _Fail())

    asyncio.run(jobs.publish_due_posts())

    assert called["n"] == 0
    db.refresh(v)
    assert v.status == PostStatus.SCHEDULED
    # Post stays SCHEDULED — nothing got posted, nothing was permanently failed.
    db.refresh(p)
    assert p.status == PostStatus.SCHEDULED


def test_tick_picks_up_variant_whose_retry_at_is_past(db, session_maker, monkeypatch, _patch_humanizer):
    from app.db import session as db_session
    from app.scheduler import jobs

    monkeypatch.setattr(db_session, "SessionLocal", session_maker, raising=True)
    monkeypatch.setattr(jobs, "SessionLocal", session_maker, raising=True)
    monkeypatch.setattr(jobs.rate_limiter, "acquire", lambda *_a, **_kw: None)

    p, v, t = _seed_post_with_variant(db)
    v.retry_count = 1
    v.retry_at = datetime.now(UTC) - timedelta(seconds=5)
    db.commit()

    class _OK:
        def adapt_content(self, t):
            return t

        async def publish(self, *a, **kw):
            return PublishResult(ok=True, external_post_id="ok-1")

    monkeypatch.setattr(jobs, "get_platform", lambda *_a, **_kw: _OK())

    asyncio.run(jobs.publish_due_posts())

    db.refresh(v)
    assert v.status == PostStatus.POSTED
    assert v.external_post_id == "ok-1"
