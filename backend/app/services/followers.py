"""Follower-count time series.

One daily snapshot per `PlatformCredential` on Meta platforms. The
scheduler calls `collect_follower_snapshots` at 02:00 UTC; the analytics
endpoint reads snapshots back and computes growth deltas over the common
7/30-day windows.

We only talk to Meta for now — LinkedIn follower counts land in a later
phase (behind its own adapter). Unknown platforms are skipped silently so
adding one later doesn't require editing this file.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import FollowerSnapshot, PlatformCredential
from app.platforms import meta_graph

log = logging.getLogger("services.followers")

# Credential platform_ids we know how to fetch for.
_META_PLATFORM_IDS = {"facebook", "instagram", "threads"}


@dataclass
class CollectResult:
    collected: int
    failed: int
    skipped: int


def fetch_followers_for_credential(cred: PlatformCredential) -> int:
    """Return current follower count for one credential.

    Delegates to `meta_graph.get_followers_count`. `is_threads=True` for
    Threads so we hit the right API base.
    """
    if cred.platform_id not in _META_PLATFORM_IDS:
        raise ValueError(f"Unsupported platform: {cred.platform_id}")
    return meta_graph.get_followers_count(
        cred.account_id,
        cred.access_token,
        is_threads=cred.platform_id == "threads",
    )


def collect_follower_snapshots(db: Session, *, now: datetime | None = None) -> CollectResult:
    """Walk credentials; one snapshot per success. Failures are logged but
    don't break the tick — a single dead token shouldn't lose snapshots
    for every other platform.
    """
    when = now or datetime.now(UTC)
    result = CollectResult(collected=0, failed=0, skipped=0)
    creds = db.query(PlatformCredential).all()
    for cred in creds:
        if cred.platform_id not in _META_PLATFORM_IDS:
            result.skipped += 1
            continue
        try:
            count = fetch_followers_for_credential(cred)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "follower fetch failed for %s/%s: %s",
                cred.platform_id,
                cred.account_id,
                exc,
            )
            result.failed += 1
            continue
        db.add(
            FollowerSnapshot(
                platform_id=cred.platform_id,
                account_id=cred.account_id,
                followers=count,
                collected_at=when,
            )
        )
        result.collected += 1
    if result.collected:
        db.commit()
    return result


# ---------- Read side ----------


@dataclass
class AccountSeries:
    """Time series + derived growth deltas for one (platform, account)."""

    platform_id: str
    account_id: str
    current: int
    # (collected_at, followers) pairs, oldest first.
    series: list[tuple[datetime, int]]
    growth_7d: int | None
    growth_30d: int | None


def _as_naive_utc(dt: datetime) -> datetime:
    """SQLite stores timezone-naive datetimes. Normalise so comparisons with
    DB-loaded values don't raise."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def _growth_over(
    series: list[tuple[datetime, int]], days: int, now: datetime
) -> int | None:
    """Change in followers between the oldest snapshot older than `days` ago
    and `current`. None if the window has no baseline yet.
    """
    if not series:
        return None
    cutoff = now - timedelta(days=days)
    baseline = None
    for collected_at, followers in series:
        if _as_naive_utc(collected_at) <= _as_naive_utc(cutoff):
            baseline = followers
        else:
            break
    if baseline is None:
        return None
    return series[-1][1] - baseline


def read_follower_series(
    db: Session,
    *,
    days: int = 30,
    now: datetime | None = None,
) -> list[AccountSeries]:
    """Per-account time series over the trailing N days, plus growth deltas
    over 7 and 30 day windows.
    """
    when = now or datetime.now(UTC)
    cutoff = _as_naive_utc(when - timedelta(days=days))
    rows = (
        db.query(FollowerSnapshot)
        .filter(FollowerSnapshot.collected_at >= cutoff)
        .order_by(
            FollowerSnapshot.platform_id.asc(),
            FollowerSnapshot.account_id.asc(),
            FollowerSnapshot.collected_at.asc(),
        )
        .all()
    )
    grouped: dict[tuple[str, str], list[FollowerSnapshot]] = defaultdict(list)
    for r in rows:
        grouped[(r.platform_id, r.account_id)].append(r)

    out: list[AccountSeries] = []
    for (platform_id, account_id), snaps in grouped.items():
        pairs = [(s.collected_at, s.followers) for s in snaps]
        out.append(
            AccountSeries(
                platform_id=platform_id,
                account_id=account_id,
                current=pairs[-1][1],
                series=pairs,
                growth_7d=_growth_over(pairs, 7, when),
                growth_30d=_growth_over(pairs, 30, when),
            )
        )
    return out
