"""M4 Humanizer tests.

Covers:
- classify_failure: checkpoint / shadow-ban / unknown
- apply_schedule_jitter: result falls in [-j, +j] minutes
- on_failure + on_success counters and smart-pause activation
- in_blackout: today vs other day
- API endpoints for profile, pause, blackouts, session-health
"""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import (
    BlackoutDate,
    HumanizerProfile,
    SessionHealth,
    SessionHealthStatus,
)
from app.services import humanizer as hz


def _make_profile(db, **overrides):
    p = HumanizerProfile(**overrides)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# ---------- Classifier ----------


@pytest.mark.parametrize(
    "reason,expected",
    [
        ("checkpoint_detected: please re-enter your password", "checkpoint"),
        ("captcha required", "checkpoint"),
        ("Please re-enter your password", "checkpoint"),
        ("Your account is temporarily blocked for violation", "shadow_ban"),
        ("unavailable: try again later", "shadow_ban"),
        ("post_button_not_found_or_disabled", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
    ],
)
def test_classify_failure(reason, expected):
    assert hz.classify_failure(reason).kind == expected


# ---------- Jitter ----------


def test_jitter_within_bounds(db):
    profile = _make_profile(db, schedule_jitter_minutes=5)
    base = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    random.seed(42)
    for _ in range(200):
        out = hz.apply_schedule_jitter(base, profile)
        delta = abs((out - base).total_seconds())
        assert delta <= 5 * 60 + 1


def test_jitter_zero_is_noop(db):
    profile = _make_profile(db, schedule_jitter_minutes=0)
    base = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert hz.apply_schedule_jitter(base, profile) == base


# ---------- Smart pause ----------


def test_pause_not_activated_below_threshold(db):
    _make_profile(db, consecutive_failures_threshold=3, smart_pause_minutes=60)
    health, _ = hz.on_failure(db, "facebook", "composer_editor_did_not_open")
    assert health.consecutive_failures == 1
    assert health.status == SessionHealthStatus.WARNING
    assert hz.check_pause(db) is None


def test_pause_activated_at_threshold(db):
    _make_profile(db, consecutive_failures_threshold=3, smart_pause_minutes=45)
    for _ in range(3):
        hz.on_failure(db, "facebook", "composer_editor_did_not_open")
    health = db.query(SessionHealth).first()
    assert health.consecutive_failures == 3
    until = hz.check_pause(db)
    assert until is not None
    delta_min = (until - datetime.now(UTC)).total_seconds() / 60
    assert 40 <= delta_min <= 46


def test_checkpoint_triggers_pause_immediately(db):
    _make_profile(db, consecutive_failures_threshold=10, smart_pause_minutes=30)
    hz.on_failure(db, "facebook", "checkpoint_detected: re-enter your password")
    until = hz.check_pause(db)
    assert until is not None


def test_on_success_resets_counter(db):
    _make_profile(db, consecutive_failures_threshold=3)
    hz.on_failure(db, "facebook", "x")
    hz.on_failure(db, "facebook", "y")
    hz.on_success(db, "facebook")
    health = db.query(SessionHealth).filter_by(platform_id="facebook").first()
    assert health.consecutive_failures == 0
    assert health.status == SessionHealthStatus.HEALTHY


def test_check_pause_auto_clears_when_expired(db):
    profile = _make_profile(db, smart_pause_minutes=30)
    profile.smart_pause_until = datetime.now(UTC) - timedelta(minutes=1)
    profile.smart_pause_reason = "old"
    db.commit()
    assert hz.check_pause(db) is None
    db.refresh(profile)
    assert profile.smart_pause_until is None
    assert profile.smart_pause_reason is None


# ---------- Blackout ----------


def test_blackout_matches_same_day(db):
    today = datetime.now(UTC).replace(hour=5, minute=0)
    db.add(BlackoutDate(date=today.replace(hour=0, minute=0), reason="holiday"))
    db.commit()
    assert hz.in_blackout(db, today) is not None


def test_blackout_does_not_match_other_day(db):
    today = datetime.now(UTC)
    other = today + timedelta(days=2)
    db.add(BlackoutDate(date=other, reason="future"))
    db.commit()
    assert hz.in_blackout(db, today) is None


# ---------- API ----------


def test_profile_get_creates_singleton(client):
    r = client.get("/api/humanizer/profile")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["typing_wpm_min"] == 35
    assert body["schedule_jitter_minutes"] == 7


def test_profile_patch_persists(client):
    client.get("/api/humanizer/profile")
    r = client.patch(
        "/api/humanizer/profile",
        json={"typing_wpm_min": 50, "mistake_rate": 0.05},
    )
    assert r.status_code == 200
    assert r.json()["typing_wpm_min"] == 50
    assert r.json()["mistake_rate"] == 0.05


def test_pause_endpoints_roundtrip(client):
    r = client.post("/api/humanizer/pause")
    assert r.status_code == 200
    assert r.json()["paused"] is True
    r = client.get("/api/humanizer/pause")
    assert r.json()["paused"] is True
    r = client.post("/api/humanizer/resume")
    assert r.json()["paused"] is False
    assert client.get("/api/humanizer/pause").json()["paused"] is False


def test_blackout_crud(client):
    r = client.post(
        "/api/humanizer/blackout-dates",
        json={"date": "2026-12-25T00:00:00Z", "reason": "Christmas"},
    )
    assert r.status_code == 201
    bid = r.json()["id"]
    assert r.json()["reason"] == "Christmas"

    listing = client.get("/api/humanizer/blackout-dates").json()
    assert len(listing) == 1

    r = client.delete(f"/api/humanizer/blackout-dates/{bid}")
    assert r.status_code == 204
    assert client.get("/api/humanizer/blackout-dates").json() == []


def test_session_health_listing(client, db):
    # Poke the service once so a row is created.
    hz.on_failure(db, "facebook", "x")
    r = client.get("/api/humanizer/session-health")
    assert r.status_code == 200
    rows = r.json()
    assert any(row["platform_id"] == "facebook" for row in rows)
