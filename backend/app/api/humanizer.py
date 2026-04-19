"""Humanizer + session health + blackout-date endpoints (M4)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.db.models import BlackoutDate, SessionHealth
from app.schemas import (
    BlackoutDateIn,
    BlackoutDateOut,
    HumanizerProfileIn,
    HumanizerProfileOut,
    SessionHealthOut,
    SmartPauseInfo,
)
from app.services import humanizer as hz

router = APIRouter(prefix="/api/humanizer", tags=["humanizer"])


@router.get("/profile", response_model=HumanizerProfileOut)
def get_profile(db: Session = Depends(get_session)) -> HumanizerProfileOut:
    return hz.get_or_create_profile(db)


@router.patch("/profile", response_model=HumanizerProfileOut)
def patch_profile(
    payload: HumanizerProfileIn, db: Session = Depends(get_session)
) -> HumanizerProfileOut:
    profile = hz.get_or_create_profile(db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/session-health", response_model=list[SessionHealthOut])
def list_session_health(db: Session = Depends(get_session)) -> list[SessionHealth]:
    return db.query(SessionHealth).order_by(SessionHealth.platform_id.asc()).all()


@router.post("/pause", response_model=SmartPauseInfo)
def activate_pause(db: Session = Depends(get_session)) -> SmartPauseInfo:
    """Manually trigger the smart pause for the configured duration."""
    profile = hz.get_or_create_profile(db)
    hz._activate_pause(profile, reason="manual pause from dashboard")
    db.commit()
    return SmartPauseInfo(
        paused=True,
        until=profile.smart_pause_until,
        reason=profile.smart_pause_reason,
    )


@router.post("/resume", response_model=SmartPauseInfo)
def clear_pause(db: Session = Depends(get_session)) -> SmartPauseInfo:
    hz.clear_pause(db)
    return SmartPauseInfo(paused=False, until=None, reason=None)


@router.get("/pause", response_model=SmartPauseInfo)
def pause_status(db: Session = Depends(get_session)) -> SmartPauseInfo:
    profile = hz.get_or_create_profile(db)
    until = hz.check_pause(db)
    return SmartPauseInfo(
        paused=until is not None,
        until=until,
        reason=profile.smart_pause_reason if until else None,
    )


@router.get("/blackout-dates", response_model=list[BlackoutDateOut])
def list_blackouts(db: Session = Depends(get_session)) -> list[BlackoutDate]:
    return db.query(BlackoutDate).order_by(BlackoutDate.date.asc()).all()


@router.post(
    "/blackout-dates",
    response_model=BlackoutDateOut,
    status_code=status.HTTP_201_CREATED,
)
def add_blackout(
    payload: BlackoutDateIn, db: Session = Depends(get_session)
) -> BlackoutDate:
    row = BlackoutDate(date=payload.date, reason=payload.reason)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/blackout-dates/{bid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_blackout(bid: int, db: Session = Depends(get_session)) -> None:
    row = db.get(BlackoutDate, bid)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(row)
    db.commit()
