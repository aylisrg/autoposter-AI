"""Phase 6b — exception hierarchy + scheduler retry loop.

Scope:
- `app.errors` hierarchy (Transient / RateLimit / Auth / Validation).
- Platform-specific classifiers (`classify_meta_error`, `classify_linkedin_error`)
  map wire-level errors to the hierarchy.
- Platform adapters (`instagram`, `threads`, `linkedin`) surface `transient`
  and `retry_after` hints on `PublishResult` when publishing fails.
- Scheduler `_publish_one` retries transient failures up to 3 times with
  1m/5m/15m backoff, then marks the variant FAILED. Non-transient failures
  are terminal on the first try.
- The `publish_due_posts` tick skips variants whose `next_retry_at` is still
  in the future.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.db.models import (
    PlatformCredential,
    Post,
    PostStatus,
    PostType,
    PostVariant,
    Target,
)
from app.errors import (
    AuthError,
    PlatformError,
    RateLimitError,
    TransientError,
    ValidationError,
)
from app.platforms import linkedin_api, meta_graph
from app.platforms.base import PublishResult
from app.platforms.instagram import InstagramPlatform
from app.platforms.linkedin import LinkedInPlatform
from app.platforms.threads import ThreadsPlatform
from app.scheduler import jobs


# ---------- Hierarchy shape ----------


def test_rate_limit_is_transient():
    e = RateLimitError("slow down", retry_after=30)
    assert isinstance(e, TransientError)
    assert isinstance(e, PlatformError)
    assert e.transient is True
    assert e.retry_after == 30


def test_transient_error_marked_retryable():
    assert TransientError("flap").transient is True


def test_auth_error_is_not_transient():
    e = AuthError("re-auth")
    assert isinstance(e, PlatformError)
    assert not isinstance(e, TransientError)
    assert e.transient is False


def test_validation_error_is_not_transient():
    e = ValidationError("bad caption")
    assert isinstance(e, PlatformError)
    assert not isinstance(e, TransientError)
    assert e.transient is False


def test_rate_limit_retry_after_defaults_to_none():
    assert RateLimitError("slow").retry_after is None


# ---------- Meta classifier ----------


def _meta_err(status: int, code: str = "1", retry_after: int | None = None):
    return meta_graph.MetaError(
        status=status, code=code, message="nope", retry_after=retry_after
    )


def test_meta_classify_429_is_rate_limit_with_retry_after():
    e = meta_graph.classify_meta_error(_meta_err(429, retry_after=45))
    assert isinstance(e, RateLimitError)
    assert e.retry_after == 45


def test_meta_classify_throttle_code_is_rate_limit():
    # Code 32 is "too many API calls". Status could be 200 with a business-code
    # error payload, so we classify on the code too.
    e = meta_graph.classify_meta_error(_meta_err(200, code="32"))
    assert isinstance(e, RateLimitError)


def test_meta_classify_expired_token_is_auth():
    # Code 190 = OAuth token expired/invalidated.
    e = meta_graph.classify_meta_error(_meta_err(400, code="190"))
    assert isinstance(e, AuthError)
    assert not e.transient


def test_meta_classify_invalid_parameter_is_validation():
    # Code 100 = invalid parameter (e.g. image_url unreachable).
    e = meta_graph.classify_meta_error(_meta_err(400, code="100"))
    assert isinstance(e, ValidationError)


def test_meta_classify_5xx_is_transient():
    e = meta_graph.classify_meta_error(_meta_err(503, code="unknown"))
    assert isinstance(e, TransientError)
    assert not isinstance(e, RateLimitError)


def test_meta_classify_unknown_4xx_is_validation():
    # Unknown 4xx without a rate-limit/auth code — default to validation so
    # the user sees a clear signal rather than silent retries.
    e = meta_graph.classify_meta_error(_meta_err(422, code="9999"))
    assert isinstance(e, ValidationError)


# ---------- LinkedIn classifier ----------


def test_linkedin_classify_429_is_rate_limit():
    exc = linkedin_api.LinkedInError(
        status=429, code="THROTTLED", message="too many", retry_after=12
    )
    e = linkedin_api.classify_linkedin_error(exc)
    assert isinstance(e, RateLimitError)
    assert e.retry_after == 12


def test_linkedin_classify_401_is_auth():
    exc = linkedin_api.LinkedInError(status=401, code="expired", message="bad token")
    e = linkedin_api.classify_linkedin_error(exc)
    assert isinstance(e, AuthError)


def test_linkedin_classify_400_is_validation():
    exc = linkedin_api.LinkedInError(status=400, code="bad", message="too long")
    e = linkedin_api.classify_linkedin_error(exc)
    assert isinstance(e, ValidationError)


def test_linkedin_classify_500_is_transient():
    exc = linkedin_api.LinkedInError(status=502, code="gw", message="bad gateway")
    e = linkedin_api.classify_linkedin_error(exc)
    assert isinstance(e, TransientError)
    assert not isinstance(e, RateLimitError)


def test_linkedin_raise_if_error_reads_retry_after_on_429():
    """_raise_if_error should populate retry_after on 429 but not on other codes."""
    import httpx

    resp_429 = httpx.Response(
        status_code=429,
        headers={"retry-after": "17"},
        json={"message": "throttled"},
    )
    with pytest.raises(linkedin_api.LinkedInError) as ei:
        linkedin_api._raise_if_error(resp_429)
    assert ei.value.retry_after == 17

    resp_500 = httpx.Response(status_code=500, json={"message": "boom"})
    with pytest.raises(linkedin_api.LinkedInError) as ei:
        linkedin_api._raise_if_error(resp_500)
    assert ei.value.retry_after is None


# ---------- Platform.publish surfaces transient hints ----------


@pytest.fixture
def _stub_cred(db):
    cred = PlatformCredential(
        platform_id="instagram", account_id="acc-x", access_token="tok"
    )
    db.add(cred)
    db.commit()
    return cred


@pytest.fixture
def _ig_target(db):
    t = Target(platform_id="instagram", external_id="ig_user_1", name="Biz IG")
    db.add(t)
    db.commit()
    return t


def _ig_post():
    return Post(
        id=1,
        post_type=PostType.INFORMATIVE,
        status=PostStatus.SCHEDULED,
        text="hello",
        image_url="https://cdn.example.com/a.jpg",
    )


def test_instagram_publish_sets_transient_on_rate_limit(db, _stub_cred, _ig_target):
    rate_limited = meta_graph.MetaError(
        status=429, code="4", message="throttled", retry_after=42
    )

    ig = InstagramPlatform(db=db)
    with patch.object(meta_graph, "ig_create_container", side_effect=rate_limited):
        result = asyncio.run(ig.publish(_ig_post(), _ig_target))

    assert not result.ok
    assert result.transient is True
    assert result.retry_after == 42
    assert "throttled" in result.error


def test_instagram_publish_marks_auth_error_non_transient(db, _stub_cred, _ig_target):
    auth_err = meta_graph.MetaError(
        status=400, code="190", message="token expired"
    )
    ig = InstagramPlatform(db=db)
    with patch.object(meta_graph, "ig_create_container", side_effect=auth_err):
        result = asyncio.run(ig.publish(_ig_post(), _ig_target))

    assert not result.ok
    assert result.transient is False
    assert result.retry_after is None


def test_instagram_publish_success_has_no_retry_hints(db, _stub_cred, _ig_target):
    ig = InstagramPlatform(db=db)
    with patch.object(meta_graph, "ig_create_container", return_value="c1"), patch.object(
        meta_graph, "ig_publish_container", return_value="media-1"
    ):
        result = asyncio.run(ig.publish(_ig_post(), _ig_target))
    assert result.ok
    assert result.transient is False
    assert result.retry_after is None


def test_threads_publish_propagates_transient_hint(db):
    db.add(
        PlatformCredential(
            platform_id="threads", account_id="tuser", access_token="tok"
        )
    )
    target = Target(platform_id="threads", external_id="tuser", name="Threads Biz")
    db.add(target)
    db.commit()

    err = meta_graph.MetaError(status=500, code="unknown", message="boom")
    th = ThreadsPlatform(db=db)
    post = Post(
        id=2,
        post_type=PostType.INFORMATIVE,
        status=PostStatus.SCHEDULED,
        text="hi threads",
    )
    with patch.object(meta_graph, "threads_create_container", side_effect=err):
        result = asyncio.run(th.publish(post, target))
    assert not result.ok
    assert result.transient is True


def test_linkedin_publish_propagates_rate_limit(db):
    db.add(
        PlatformCredential(
            platform_id="linkedin", account_id="abc123", access_token="tok"
        )
    )
    target = Target(platform_id="linkedin", external_id="abc123", name="LI me")
    db.add(target)
    db.commit()

    err = linkedin_api.LinkedInError(
        status=429, code="THROTTLED", message="slow", retry_after=99
    )
    li = LinkedInPlatform(db=db)
    post = Post(
        id=3,
        post_type=PostType.INFORMATIVE,
        status=PostStatus.SCHEDULED,
        text="professional opinion",
    )
    with patch.object(linkedin_api, "create_text_post", side_effect=err):
        result = asyncio.run(li.publish(post, target))

    assert not result.ok
    assert result.transient is True
    assert result.retry_after == 99


# ---------- Scheduler retry behaviour ----------


class _FakePlatform:
    """Drop-in replacement for platform objects in _publish_one tests."""

    def __init__(self, result_sequence):
        self._results = list(result_sequence)
        self.calls = 0
        self.id = "fake"

    def adapt_content(self, text):
        return text

    async def publish(self, post, target, humanizer=None):
        self.calls += 1
        return self._results.pop(0)


def _make_post_variant(db):
    """A minimal SCHEDULED post + one variant attached to a dummy target."""
    post = Post(
        id=None,
        post_type=PostType.INFORMATIVE,
        status=PostStatus.SCHEDULED,
        text="hi",
        image_url="https://cdn.example.com/x.jpg",
    )
    db.add(post)
    db.flush()
    target = Target(platform_id="fake", external_id="t1", name="dst")
    db.add(target)
    db.flush()
    variant = PostVariant(
        post_id=post.id,
        target_id=target.id,
        text="hi",
        status=PostStatus.SCHEDULED,
    )
    db.add(variant)
    db.commit()
    return post, variant, target


def test_transient_failure_schedules_retry_at_60s(db):
    post, variant, target = _make_post_variant(db)
    fake = _FakePlatform(
        [PublishResult(ok=False, error="timeout", transient=True)]
    )
    with patch.object(jobs, "get_platform", return_value=fake):
        before = datetime.now(UTC)
        asyncio.run(jobs._publish_one(post, variant, target))

    assert variant.status == PostStatus.SCHEDULED
    assert variant.attempt_count == 1
    assert variant.next_retry_at is not None
    # First retry is ~60s out. Allow a few seconds of slack.
    delta = (variant.next_retry_at - before).total_seconds()
    assert 55 <= delta <= 75


def test_transient_failure_honours_retry_after_hint(db):
    post, variant, target = _make_post_variant(db)
    fake = _FakePlatform(
        [PublishResult(ok=False, error="throttle", transient=True, retry_after=200)]
    )
    with patch.object(jobs, "get_platform", return_value=fake):
        before = datetime.now(UTC)
        asyncio.run(jobs._publish_one(post, variant, target))

    assert variant.status == PostStatus.SCHEDULED
    delta = (variant.next_retry_at - before).total_seconds()
    # Hint should override the default 60s.
    assert 190 <= delta <= 215


def test_non_transient_failure_is_terminal_on_first_try(db):
    post, variant, target = _make_post_variant(db)
    fake = _FakePlatform(
        [PublishResult(ok=False, error="bad creds", transient=False)]
    )
    with patch.object(jobs, "get_platform", return_value=fake):
        asyncio.run(jobs._publish_one(post, variant, target))

    assert variant.status == PostStatus.FAILED
    assert variant.attempt_count == 1
    assert variant.next_retry_at is None
    assert "bad creds" in variant.error


def test_retry_gives_up_after_three_attempts(db):
    post, variant, target = _make_post_variant(db)
    # Simulate three consecutive transient failures.
    fake = _FakePlatform(
        [
            PublishResult(ok=False, error="f1", transient=True),
            PublishResult(ok=False, error="f2", transient=True),
            PublishResult(ok=False, error="f3", transient=True),
            PublishResult(ok=False, error="f4", transient=True),
        ]
    )
    with patch.object(jobs, "get_platform", return_value=fake):
        # Call _publish_one four times — simulating four scheduler ticks.
        for _ in range(4):
            asyncio.run(jobs._publish_one(post, variant, target))

    assert variant.status == PostStatus.FAILED
    assert variant.attempt_count == 4
    assert variant.next_retry_at is None
    assert variant.error == "f4"


def test_backoff_sequence_is_1m_5m_15m(db):
    post, variant, target = _make_post_variant(db)
    expected = [60, 300, 900]
    for i, want in enumerate(expected, start=1):
        fake = _FakePlatform(
            [PublishResult(ok=False, error=f"t{i}", transient=True)]
        )
        before = datetime.now(UTC)
        with patch.object(jobs, "get_platform", return_value=fake):
            asyncio.run(jobs._publish_one(post, variant, target))
        assert variant.attempt_count == i
        delta = (variant.next_retry_at - before).total_seconds()
        assert abs(delta - want) < 10, (
            f"attempt {i}: expected backoff ~{want}s, got {delta}"
        )


def test_success_clears_retry_state(db):
    post, variant, target = _make_post_variant(db)
    # Pretend we already failed once.
    variant.attempt_count = 1
    variant.next_retry_at = datetime.now(UTC) + timedelta(seconds=30)
    db.commit()

    fake = _FakePlatform(
        [PublishResult(ok=True, external_post_id="live-1")]
    )
    with patch.object(jobs, "get_platform", return_value=fake):
        asyncio.run(jobs._publish_one(post, variant, target))

    assert variant.status == PostStatus.POSTED
    assert variant.external_post_id == "live-1"
    assert variant.next_retry_at is None
    assert variant.error is None


def test_unknown_platform_is_terminal(db):
    post, variant, target = _make_post_variant(db)
    target.platform_id = "who-knows"
    db.commit()
    with patch.object(jobs, "get_platform", return_value=None):
        asyncio.run(jobs._publish_one(post, variant, target))
    assert variant.status == PostStatus.FAILED
    assert variant.next_retry_at is None
    assert "Unknown platform_id" in variant.error


def test_adapter_exception_treated_as_transient(db):
    post, variant, target = _make_post_variant(db)

    class _Boom:
        id = "fake"

        def adapt_content(self, t):
            return t

        async def publish(self, *a, **kw):
            raise RuntimeError("network blew up")

    with patch.object(jobs, "get_platform", return_value=_Boom()):
        asyncio.run(jobs._publish_one(post, variant, target))

    # Adapter raised instead of returning → we retry.
    assert variant.status == PostStatus.SCHEDULED
    assert variant.attempt_count == 1
    assert variant.next_retry_at is not None
    assert "network blew up" in variant.error
