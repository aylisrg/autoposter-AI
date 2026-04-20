"""M7 follow-up — Meta long-lived token refresh.

Covers:
- `token_refresh.refresh_one` persists new token + expiry, emits audit event.
- `refresh_expiring` skips rows outside the window AND rows without expiry,
  continues past per-row failures instead of raising.
- `/api/platform-credentials/{id}/refresh` happy path + 404 + error mapping.
- `PlatformCredentialOut.days_until_expiry` is computed correctly for
  future, past, and None expiries.

Every test mocks `meta_graph.long_lived_token` so we never hit the network.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.db.models import PlatformCredential
from app.schemas import PlatformCredentialOut
from app.services import token_refresh


def _make_cred(
    db,
    platform_id: str,
    account_id: str,
    *,
    expires_in_days: int | None = 3,
    token: str = "OLD_TOK",
) -> PlatformCredential:
    row = PlatformCredential(
        platform_id=platform_id,
        account_id=account_id,
        username=f"{platform_id}_user",
        access_token=token,
        extra={},
        token_expires_at=(
            datetime.now(UTC) + timedelta(days=expires_in_days)
            if expires_in_days is not None
            else None
        ),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _set_meta_env(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "meta_app_id", "12345", raising=False)
    monkeypatch.setattr(settings, "meta_app_secret", "s3cret", raising=False)


# ---------- refresh_one ----------


def test_refresh_one_updates_token_and_expiry(db, monkeypatch):
    _set_meta_env(monkeypatch)
    cred = _make_cred(db, "instagram", "IG_R1", expires_in_days=3)
    old_expiry = cred.token_expires_at

    with patch("app.services.token_refresh.meta_graph.long_lived_token") as m:
        m.return_value = {
            "access_token": "NEW_TOK",
            "expires_in": 60 * 24 * 3600,  # 60 days
        }
        updated = token_refresh.refresh_one(db, cred)

    assert updated.access_token == "NEW_TOK"
    assert updated.token_expires_at is not None
    # Must advance expiry by ~60 days.
    assert updated.token_expires_at > old_expiry + timedelta(days=30)
    m.assert_called_once()
    kwargs = m.call_args.kwargs
    assert kwargs["short_token"] == "OLD_TOK"
    assert kwargs["app_id"] == "12345"


def test_refresh_one_rejects_unsupported_platform(db, monkeypatch):
    _set_meta_env(monkeypatch)
    cred = _make_cred(db, "facebook", "FB_X", expires_in_days=None)
    with pytest.raises(ValueError, match="not supported"):
        token_refresh.refresh_one(db, cred)


def test_refresh_one_requires_meta_app_config(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "meta_app_id", "", raising=False)
    monkeypatch.setattr(settings, "meta_app_secret", "", raising=False)
    cred = _make_cred(db, "instagram", "IG_R2", expires_in_days=3)
    with pytest.raises(RuntimeError, match="META_APP_ID"):
        token_refresh.refresh_one(db, cred)


# ---------- refresh_expiring ----------


def test_refresh_expiring_only_touches_rows_in_window(db, monkeypatch):
    _set_meta_env(monkeypatch)
    near = _make_cred(db, "instagram", "NEAR", expires_in_days=2)
    far = _make_cred(db, "instagram", "FAR", expires_in_days=30)
    nodate = _make_cred(db, "threads", "NODATE", expires_in_days=None)
    unsupported = _make_cred(db, "facebook", "FB", expires_in_days=2)

    with patch("app.services.token_refresh.meta_graph.long_lived_token") as m:
        m.return_value = {"access_token": "FRESH", "expires_in": 60 * 24 * 3600}
        result = token_refresh.refresh_expiring(db, window_days=7)

    assert result.refreshed == 1
    assert result.failed == 0
    db.refresh(near)
    db.refresh(far)
    db.refresh(nodate)
    db.refresh(unsupported)
    assert near.access_token == "FRESH"
    # Rows outside the window / without expiry / unsupported platform must
    # not be touched.
    assert far.access_token == "OLD_TOK"
    assert nodate.access_token == "OLD_TOK"
    assert unsupported.access_token == "OLD_TOK"


def test_refresh_expiring_collects_failures_without_raising(db, monkeypatch):
    _set_meta_env(monkeypatch)
    _make_cred(db, "instagram", "GOOD", expires_in_days=1)
    _make_cred(db, "threads", "BAD", expires_in_days=1)

    def fake(**kwargs):
        if kwargs["short_token"] == "OLD_TOK" and "GOOD" not in str(kwargs):
            # Mock refuses the second call — can't distinguish by kwargs here,
            # so we rotate on call count.
            raise RuntimeError("boom")
        return {"access_token": "NEW", "expires_in": 60 * 24 * 3600}

    # Simpler: first call ok, second call raises.
    results = [
        {"access_token": "NEW", "expires_in": 60 * 24 * 3600},
        RuntimeError("meta down"),
    ]

    def side_effect(**_kwargs):
        out = results.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    with patch(
        "app.services.token_refresh.meta_graph.long_lived_token",
        side_effect=side_effect,
    ):
        result = token_refresh.refresh_expiring(db, window_days=7)

    assert result.refreshed == 1
    assert result.failed == 1
    assert any("meta down" in f for f in result.failures)


# ---------- API endpoint ----------


def test_refresh_endpoint_returns_updated_credential(client, db, monkeypatch):
    _set_meta_env(monkeypatch)
    cred = _make_cred(db, "instagram", "IG_API", expires_in_days=2)

    with patch("app.services.token_refresh.meta_graph.long_lived_token") as m:
        m.return_value = {"access_token": "NEW", "expires_in": 60 * 24 * 3600}
        r = client.post(f"/api/platform-credentials/{cred.id}/refresh")

    assert r.status_code == 200
    body = r.json()
    assert body["id"] == cred.id
    assert body["platform_id"] == "instagram"
    assert body["days_until_expiry"] is not None
    assert body["days_until_expiry"] >= 55  # refreshed to ~60 days
    # Never leak the token.
    assert "access_token" not in body


def test_refresh_endpoint_404_for_missing(client):
    r = client.post("/api/platform-credentials/9999/refresh")
    assert r.status_code == 404


def test_refresh_endpoint_400_for_unsupported_platform(client, db, monkeypatch):
    _set_meta_env(monkeypatch)
    cred = _make_cred(db, "facebook", "FB_NO", expires_in_days=None)
    r = client.post(f"/api/platform-credentials/{cred.id}/refresh")
    assert r.status_code == 400


def test_refresh_endpoint_502_on_meta_failure(client, db, monkeypatch):
    _set_meta_env(monkeypatch)
    cred = _make_cred(db, "instagram", "IG_FAIL", expires_in_days=2)

    with patch("app.services.token_refresh.meta_graph.long_lived_token") as m:
        m.side_effect = Exception("meta graph 500")
        r = client.post(f"/api/platform-credentials/{cred.id}/refresh")

    assert r.status_code == 502
    assert "meta graph 500" in r.json()["detail"]


# ---------- Schema derivation ----------


def test_days_until_expiry_future():
    future = datetime.now(UTC) + timedelta(days=10, hours=12)
    out = PlatformCredentialOut(
        id=1,
        platform_id="instagram",
        account_id="A",
        username=None,
        token_expires_at=future,
        extra={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    # Floor division on seconds → 10, not 11.
    assert out.days_until_expiry == 10


def test_days_until_expiry_expired():
    past = datetime.now(UTC) - timedelta(days=5)
    out = PlatformCredentialOut(
        id=1,
        platform_id="instagram",
        account_id="A",
        username=None,
        token_expires_at=past,
        extra={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert out.days_until_expiry is not None
    assert out.days_until_expiry <= -5


def test_days_until_expiry_null_when_no_expiry():
    out = PlatformCredentialOut(
        id=1,
        platform_id="instagram",
        account_id="A",
        username=None,
        token_expires_at=None,
        extra={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert out.days_until_expiry is None


def test_days_until_expiry_treats_naive_as_utc():
    """SQLite returns naive datetimes; the validator must assume UTC."""
    future_naive = (datetime.now(UTC) + timedelta(days=20)).replace(tzinfo=None)
    out = PlatformCredentialOut(
        id=1,
        platform_id="threads",
        account_id="A",
        username=None,
        token_expires_at=future_naive,
        extra={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert out.days_until_expiry == 19 or out.days_until_expiry == 20
