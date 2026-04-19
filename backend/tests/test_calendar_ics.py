"""Phase 5a — iCalendar feed.

Covers:
- Empty DB returns a well-formed (but eventless) VCALENDAR.
- A scheduled post renders a VEVENT with matching DTSTART / SUMMARY.
- Wrong / missing token is rejected with 401 when a PIN is configured.
- No-PIN dev mode skips token enforcement.
- /subscribe-url returns the URL the dashboard should show.
- RFC 5545 TEXT-escaping survives commas, semicolons, backslashes, newlines.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.api import calendar_ics
from app.db.models import Post, PostStatus, PostType, PostVariant, Target


# ---------- Helpers ----------


def _seed_post(
    db,
    *,
    scheduled_for: datetime | None = None,
    posted_at: datetime | None = None,
    text: str = "Hello, world.",
    post_type: PostType = PostType.INFORMATIVE,
    status: PostStatus = PostStatus.SCHEDULED,
) -> Post:
    target = Target(
        platform_id="facebook",
        external_id=f"https://fb/group/{text[:8]}",
        name="Test Group",
        tags=[],
        active=True,
        source="manual",
    )
    db.add(target)
    db.flush()
    post = Post(
        post_type=post_type,
        status=status,
        text=text,
        scheduled_for=scheduled_for,
        posted_at=posted_at,
    )
    db.add(post)
    db.flush()
    db.add(
        PostVariant(
            post_id=post.id,
            target_id=target.id,
            text=text,
            status=status,
            scheduled_for=scheduled_for,
        )
    )
    db.commit()
    db.refresh(post)
    return post


def _ics_header_ok(body: str) -> None:
    assert body.startswith("BEGIN:VCALENDAR\r\n")
    assert body.rstrip("\r\n").endswith("END:VCALENDAR")
    assert "VERSION:2.0" in body
    assert "PRODID:" in body
    # All newlines must be CRLF.
    assert "\r\n" in body
    stripped = body.replace("\r\n", "")
    assert "\n" not in stripped


# ---------- Token ----------


def test_token_is_stable_for_same_pin():
    a = calendar_ics.make_calendar_token("1234")
    b = calendar_ics.make_calendar_token("1234")
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_token_changes_with_pin():
    assert calendar_ics.make_calendar_token("1234") != calendar_ics.make_calendar_token(
        "4321"
    )


# ---------- Serialization ----------


def test_render_empty_calendar():
    body = calendar_ics._render_calendar([], {})
    _ics_header_ok(body)
    assert "BEGIN:VEVENT" not in body


def test_render_single_event_fields():
    start = datetime(2026, 5, 1, 14, 30, tzinfo=UTC)
    post = Post(
        id=42,
        post_type=PostType.INFORMATIVE,
        status=PostStatus.SCHEDULED,
        text="Launch day!",
        scheduled_for=start,
        created_at=datetime(2026, 4, 20, 10, 0, tzinfo=UTC),
    )
    post.variants = []
    body = calendar_ics._render_calendar([post], {})
    _ics_header_ok(body)
    assert "BEGIN:VEVENT" in body
    assert "UID:autoposter-post-42@autoposter" in body
    assert "DTSTART:20260501T143000Z" in body
    # +15 min default duration.
    assert "DTEND:20260501T144500Z" in body
    assert "SUMMARY:[informative] Launch day!" in body
    assert "STATUS:TENTATIVE" in body
    assert "TRANSP:TRANSPARENT" in body


def test_render_posted_event_uses_posted_at_and_confirmed():
    posted = datetime(2026, 4, 1, 9, 0, tzinfo=UTC)
    post = Post(
        id=1,
        post_type=PostType.HARD_SELL,
        status=PostStatus.POSTED,
        text="shipped",
        posted_at=posted,
        created_at=posted,
    )
    post.variants = []
    body = calendar_ics._render_calendar([post], {})
    assert "DTSTART:20260401T090000Z" in body
    assert "STATUS:CONFIRMED" in body


def test_escape_handles_ical_special_chars():
    assert calendar_ics._escape("a,b;c\\d\ne") == "a\\,b\\;c\\\\d\\ne"


def test_fold_long_line():
    long = "x" * 200
    folded = calendar_ics._fold(long)
    # Continuation lines begin with a single space, and no physical line
    # exceeds the fold width.
    for phys in folded.split("\r\n"):
        assert len(phys) <= calendar_ics._FOLD_WIDTH + 1  # +1 for leading space


# ---------- HTTP surface ----------


@pytest.fixture()
def _no_pin(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "dashboard_pin", "", raising=False)


@pytest.fixture()
def _with_pin(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "dashboard_pin", "test-pin", raising=False)


def test_calendar_ics_empty_db_no_pin(client, _no_pin):
    r = client.get("/api/calendar.ics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar")
    _ics_header_ok(r.text)
    assert "BEGIN:VEVENT" not in r.text


def test_calendar_ics_includes_scheduled_post(client, db, _no_pin):
    when = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    post = _seed_post(db, scheduled_for=when, text="Big announcement; exciting!")
    r = client.get("/api/calendar.ics")
    assert r.status_code == 200
    body = r.text
    assert f"UID:autoposter-post-{post.id}@autoposter" in body
    assert "DTSTART:20260601T120000Z" in body
    # Semicolon must be escaped in SUMMARY.
    assert "Big announcement\\; exciting!" in body


def test_calendar_ics_requires_token_when_pin_set(client, _with_pin):
    r = client.get("/api/calendar.ics")
    assert r.status_code == 401


def test_calendar_ics_rejects_wrong_token(client, _with_pin):
    r = client.get("/api/calendar.ics?token=deadbeef")
    assert r.status_code == 401


def test_calendar_ics_accepts_correct_token(client, _with_pin):
    token = calendar_ics.make_calendar_token("test-pin")
    r = client.get(f"/api/calendar.ics?token={token}")
    assert r.status_code == 200
    _ics_header_ok(r.text)


def test_subscribe_url_no_pin(client, _no_pin):
    r = client.get("/api/calendar/subscribe-url")
    assert r.status_code == 200
    body = r.json()
    assert body == {"url": "/api/calendar.ics", "auth_required": False}


def test_subscribe_url_with_pin_includes_token(client, _with_pin):
    r = client.get(
        "/api/calendar/subscribe-url",
        headers={"X-Dashboard-Pin": "test-pin"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["auth_required"] is True
    token = calendar_ics.make_calendar_token("test-pin")
    assert body["url"] == f"/api/calendar.ics?token={token}"


def test_posts_without_scheduling_are_skipped(client, db, _no_pin):
    # Draft with no scheduled_for and no posted_at shouldn't appear.
    _seed_post(db, text="draft-only", status=PostStatus.DRAFT)
    r = client.get("/api/calendar.ics")
    assert r.status_code == 200
    assert "BEGIN:VEVENT" not in r.text


def test_event_includes_target_names(client, db, _no_pin):
    when = datetime.now(UTC) + timedelta(days=1)
    _seed_post(db, scheduled_for=when, text="targeted post")
    r = client.get("/api/calendar.ics")
    assert "Targets: Test Group" in r.text
