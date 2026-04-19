"""Phase 5c — follower-count time series.

Covers:
- meta_graph.get_followers_count hits the right API base (graph vs
  threads) and returns the int field.
- collect_follower_snapshots writes rows for supported platforms, skips
  unsupported ones, and swallows individual fetch failures so one dead
  token doesn't break the whole tick.
- read_follower_series groups by (platform, account), orders oldest-first,
  and computes 7/30-day deltas only when a baseline exists.
- GET /api/followers returns the series + username labels; /collect
  triggers the sync path.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import FollowerSnapshot, PlatformCredential
from app.platforms import meta_graph
from app.services import followers as followers_service


# ---------- meta_graph ----------


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.headers: dict[str, str] = {}
        self.text = ""

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload: dict, captured_url: list[str]):
        self._payload = payload
        self._captured = captured_url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None):
        self._captured.append(url)
        return _FakeResponse(200, self._payload)


def test_get_followers_count_graph(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(
        meta_graph.httpx,
        "Client",
        lambda **kw: _FakeClient({"followers_count": 42}, captured),
    )
    n = meta_graph.get_followers_count("17841000", "token")
    assert n == 42
    assert captured[0].startswith(meta_graph.GRAPH_BASE + "/17841000")


def test_get_followers_count_threads(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(
        meta_graph.httpx,
        "Client",
        lambda **kw: _FakeClient({"followers_count": 7}, captured),
    )
    n = meta_graph.get_followers_count("999", "token", is_threads=True)
    assert n == 7
    assert captured[0].startswith(meta_graph.THREADS_BASE + "/999")


def test_get_followers_count_missing_field_returns_zero(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(
        meta_graph.httpx,
        "Client",
        lambda **kw: _FakeClient({"id": "1"}, captured),
    )
    assert meta_graph.get_followers_count("1", "t") == 0


# ---------- service ----------


def _seed_cred(db, *, platform_id: str, account_id: str, username: str | None = None) -> PlatformCredential:
    c = PlatformCredential(
        platform_id=platform_id,
        account_id=account_id,
        username=username,
    )
    c.access_token = "fake-token"
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def test_collect_writes_snapshot_per_supported_credential(db, monkeypatch):
    _seed_cred(db, platform_id="instagram", account_id="ig-1")
    _seed_cred(db, platform_id="threads", account_id="th-1")
    _seed_cred(db, platform_id="unknown", account_id="u-1")

    counts = iter([100, 200])
    monkeypatch.setattr(
        followers_service,
        "fetch_followers_for_credential",
        lambda cred: next(counts),
    )

    result = followers_service.collect_follower_snapshots(db)
    assert result.collected == 2
    assert result.skipped == 1
    assert result.failed == 0

    rows = db.query(FollowerSnapshot).all()
    by_platform = {r.platform_id: r.followers for r in rows}
    assert by_platform == {"instagram": 100, "threads": 200}


def test_collect_isolates_fetch_failures(db, monkeypatch):
    _seed_cred(db, platform_id="instagram", account_id="ig-1")
    _seed_cred(db, platform_id="facebook", account_id="fb-1")

    def fake(cred):
        if cred.platform_id == "instagram":
            raise RuntimeError("token expired")
        return 500

    monkeypatch.setattr(followers_service, "fetch_followers_for_credential", fake)
    result = followers_service.collect_follower_snapshots(db)
    assert result.collected == 1
    assert result.failed == 1
    # Only the successful fetch was persisted.
    rows = db.query(FollowerSnapshot).all()
    assert [(r.platform_id, r.followers) for r in rows] == [("facebook", 500)]


# ---------- read side ----------


def _seed_snap(
    db, platform_id: str, account_id: str, when: datetime, followers: int
) -> None:
    db.add(
        FollowerSnapshot(
            platform_id=platform_id,
            account_id=account_id,
            followers=followers,
            collected_at=when,
        )
    )


def test_read_series_groups_and_computes_growth(db):
    now = datetime(2026, 4, 30, tzinfo=UTC)
    _seed_snap(db, "instagram", "ig-1", now - timedelta(days=31), 900)
    _seed_snap(db, "instagram", "ig-1", now - timedelta(days=8), 950)
    _seed_snap(db, "instagram", "ig-1", now - timedelta(days=1), 1000)
    db.commit()

    series = followers_service.read_follower_series(db, days=60, now=now)
    assert len(series) == 1
    s = series[0]
    assert s.platform_id == "instagram"
    assert s.account_id == "ig-1"
    assert s.current == 1000
    assert [f for _, f in s.series] == [900, 950, 1000]
    # 7d baseline = 950 (-8d snapshot is the most recent one older than 7d ago) → 1000 - 950 = 50
    assert s.growth_7d == 50
    # 30d baseline = 900 → 1000 - 900 = 100
    assert s.growth_30d == 100


def test_read_series_growth_null_without_baseline(db):
    now = datetime(2026, 4, 30, tzinfo=UTC)
    # Only a single snapshot within the 7-day window — no baseline yet.
    _seed_snap(db, "threads", "th-1", now - timedelta(hours=3), 100)
    db.commit()

    series = followers_service.read_follower_series(db, days=60, now=now)
    assert len(series) == 1
    assert series[0].growth_7d is None
    assert series[0].growth_30d is None


def test_read_series_respects_days_cutoff(db):
    now = datetime(2026, 4, 30, tzinfo=UTC)
    _seed_snap(db, "instagram", "ig-1", now - timedelta(days=40), 800)
    _seed_snap(db, "instagram", "ig-1", now - timedelta(days=1), 900)
    db.commit()

    series = followers_service.read_follower_series(db, days=10, now=now)
    assert len(series) == 1
    # Only the -1d snapshot is within the window.
    assert [f for _, f in series[0].series] == [900]


# ---------- HTTP surface ----------


@pytest.fixture()
def _mute_fetch(monkeypatch):
    monkeypatch.setattr(
        followers_service,
        "fetch_followers_for_credential",
        lambda cred: 1234,
    )


def test_api_list_followers_includes_username(client, db):
    _seed_cred(db, platform_id="instagram", account_id="ig-1", username="acme")
    _seed_snap(db, "instagram", "ig-1", datetime.now(UTC), 500)
    db.commit()

    r = client.get("/api/followers?days=30")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["username"] == "acme"
    assert body[0]["current"] == 500


def test_api_list_followers_validates_days(client):
    r = client.get("/api/followers?days=0")
    assert r.status_code == 422
    r = client.get("/api/followers?days=400")
    assert r.status_code == 422


def test_api_collect_now_runs_service(client, db, _mute_fetch):
    _seed_cred(db, platform_id="facebook", account_id="fb-1")
    r = client.post("/api/followers/collect")
    assert r.status_code == 200
    body = r.json()
    assert body == {"collected": 1, "failed": 0, "skipped": 0}
    # Persisted.
    assert db.query(FollowerSnapshot).count() == 1
