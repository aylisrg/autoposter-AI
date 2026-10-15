"""Business profile CRUD. Singleton for v1 — we always upsert row with id=1."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_current_profile, get_session, invalidate_profile_cache
from app.db.models import (
    BusinessProfile,
    Post,
    PostStatus,
    PostType,
    ReviewQueueItem,
    ReviewQueueStatus,
)
from app.schemas import BusinessProfileIn, BusinessProfileOut, BusinessProfilePatch

router = APIRouter(prefix="/api/business-profile", tags=["business-profile"])

# Statuses a post reaches only after a clean approval (or auto-approve).
# Skips, failures, and still-pending posts do not count toward the suggestion.
_CLEAN_APPROVAL_STATUSES = (
    PostStatus.DRAFT,
    PostStatus.SCHEDULED,
    PostStatus.POSTING,
    PostStatus.POSTED,
)


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


@router.get("/suggestions")
def get_auto_approve_suggestions(
    profile: BusinessProfile | None = Depends(get_current_profile),
    db: Session = Depends(get_session),
) -> dict:
    """Suggest types whose last N approvals were made without edits.

    Issue #35: per post type, if the most recent ``auto_approve_threshold``
    approvals (default 10) contain no edits, the UI can offer to turn
    auto-approve on. Rejects, skips, and failed posts do not count.
    """
    threshold = settings.auto_approve_threshold
    if profile is None:
        return {"suggested_types": [], "threshold": threshold}

    already = set(profile.auto_approve_types or [])
    suggested: list[str] = []
    for ptype in PostType:
        if ptype.value in already:
            continue
        recent_ids = [
            row[0]
            for row in (
                db.query(Post.id)
                .filter(
                    Post.post_type == ptype,
                    Post.status.in_(_CLEAN_APPROVAL_STATUSES),
                )
                .order_by(Post.created_at.desc(), Post.id.desc())
                .limit(threshold)
                .all()
            )
        ]
        if len(recent_ids) < threshold:
            continue
        edited = (
            db.query(ReviewQueueItem.id)
            .filter(
                ReviewQueueItem.post_id.in_(recent_ids),
                ReviewQueueItem.status == ReviewQueueStatus.EDITED,
            )
            .first()
        )
        if edited is not None:
            continue
        suggested.append(ptype.value)

    return {"suggested_types": suggested, "threshold": threshold}
