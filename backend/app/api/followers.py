"""Follower-count time series endpoints.

- GET /api/followers — per-account trailing time series with 7d/30d deltas.
  Feeds the dashboard growth chart.
- POST /api/followers/collect — manual trigger. Normally the scheduler
  hits this code path at 02:00 UTC; the endpoint exists so the user can
  pull an ad-hoc snapshot without waiting for the next tick.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_session
from app.db.models import PlatformCredential
from app.services import followers as followers_service

router = APIRouter(prefix="/api/followers", tags=["followers"])


class FollowerSnapshotOut(BaseModel):
    collected_at: datetime
    followers: int


class FollowerSeriesOut(BaseModel):
    platform_id: str
    account_id: str
    username: str | None
    current: int
    # Oldest first — the dashboard plots left-to-right.
    series: list[FollowerSnapshotOut]
    # Null when the window doesn't yet have a baseline snapshot
    # (e.g. a brand-new connection).
    growth_7d: int | None
    growth_30d: int | None


class CollectFollowersResult(BaseModel):
    collected: int
    failed: int
    skipped: int


@router.get("", response_model=list[FollowerSeriesOut])
def list_followers(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_session),
) -> list[FollowerSeriesOut]:
    series = followers_service.read_follower_series(db, days=days)
    # Pull usernames from credentials in one query so the dashboard can label
    # accounts with something human-readable instead of raw IDs.
    creds = {
        (c.platform_id, c.account_id): c.username
        for c in db.query(PlatformCredential).all()
    }
    return [
        FollowerSeriesOut(
            platform_id=s.platform_id,
            account_id=s.account_id,
            username=creds.get((s.platform_id, s.account_id)),
            current=s.current,
            series=[
                FollowerSnapshotOut(collected_at=dt, followers=f)
                for dt, f in s.series
            ],
            growth_7d=s.growth_7d,
            growth_30d=s.growth_30d,
        )
        for s in series
    ]


@router.post("/collect", response_model=CollectFollowersResult)
async def collect_now(db: Session = Depends(get_session)) -> CollectFollowersResult:
    try:
        result = await asyncio.to_thread(
            followers_service.collect_follower_snapshots, db
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return CollectFollowersResult(
        collected=result.collected, failed=result.failed, skipped=result.skipped
    )
