"""Business profile CRUD. Singleton for v1 — we always upsert row with id=1."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_current_profile, get_session, invalidate_profile_cache
from app.db.models import BusinessProfile
from app.schemas import BusinessProfileIn, BusinessProfileOut, BusinessProfilePatch

router = APIRouter(prefix="/api/business-profile", tags=["business-profile"])


@router.get("", response_model=BusinessProfileOut)
def get_profile(
    profile: BusinessProfile | None = Depends(get_current_profile),
) -> BusinessProfile:
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business profile not set yet. PUT to create it.",
        )
    return profile


@router.post("", response_model=BusinessProfileOut, status_code=status.HTTP_201_CREATED)
def create_profile(
    payload: BusinessProfileIn,
    db: Session = Depends(get_session),
) -> BusinessProfile:
    existing = get_current_profile(db)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Business profile already exists. Use PUT or PATCH.",
        )
    profile = BusinessProfile(**payload.model_dump())
    db.add(profile)
    db.commit()
    db.refresh(profile)
    invalidate_profile_cache()
    return profile


@router.put("", response_model=BusinessProfileOut)
def upsert_profile(
    payload: BusinessProfileIn,
    db: Session = Depends(get_session),
) -> BusinessProfile:
    profile = get_current_profile(db)
    if profile is None:
        profile = BusinessProfile(**payload.model_dump())
        db.add(profile)
    else:
        for key, value in payload.model_dump().items():
            setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    invalidate_profile_cache()
    return profile


@router.patch("", response_model=BusinessProfileOut)
def patch_profile(
    payload: BusinessProfilePatch,
    db: Session = Depends(get_session),
) -> BusinessProfile:
    profile = get_current_profile(db)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business profile not set yet.",
        )
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    invalidate_profile_cache()
    return profile


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(db: Session = Depends(get_session)) -> None:
    profile = get_current_profile(db)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business profile not set yet.",
        )
    db.delete(profile)
    db.commit()
    invalidate_profile_cache()


from app.config import settings
from app.db.models import Post, PostStatus, PostType


@router.get("/suggestions")
def get_auto_approve_suggestions(
    profile: BusinessProfile | None = Depends(get_current_profile),
    db: Session = Depends(get_session),
) -> dict:
    """Return post types that have reached the approval threshold and are not yet auto-approved.

    Threshold defaults to 10 recent non-pending-review posts of that type.
    """
    if profile is None:
        return {"suggested_types": [], "threshold": 10}

    threshold = settings.auto_approve_threshold
    already = set(profile.auto_approve_types or [])

    suggested: list[str] = []
    for ptype in PostType:
        if ptype.value in already:
            continue
        recent = (
            db.query(Post.id)
            .filter(
                Post.post_type == ptype,
                Post.status != PostStatus.PENDING_REVIEW,
            )
            .order_by(Post.created_at.desc())
            .limit(threshold)
            .all()
        )
        if len(recent) >= threshold:
            suggested.append(ptype.value)

    return {"suggested_types": suggested, "threshold": threshold}
