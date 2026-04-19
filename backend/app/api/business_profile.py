"""Business profile CRUD. Singleton for v1 — we always upsert row with id=1."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.db.models import BusinessProfile
from app.schemas import BusinessProfileIn, BusinessProfileOut

router = APIRouter(prefix="/api/business-profile", tags=["business-profile"])


@router.get("", response_model=BusinessProfileOut)
def get_profile(db: Session = Depends(get_session)) -> BusinessProfile:
    profile = db.query(BusinessProfile).order_by(BusinessProfile.id.asc()).first()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business profile not set yet. PUT to create it.",
        )
    return profile


@router.put("", response_model=BusinessProfileOut)
def upsert_profile(
    payload: BusinessProfileIn,
    db: Session = Depends(get_session),
) -> BusinessProfile:
    profile = db.query(BusinessProfile).order_by(BusinessProfile.id.asc()).first()
    if profile is None:
        profile = BusinessProfile(**payload.model_dump())
        db.add(profile)
    else:
        for key, value in payload.model_dump().items():
            setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    return profile
