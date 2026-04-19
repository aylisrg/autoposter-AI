"""Target CRUD + sync-from-extension.

A Target is a place we post to (FB group URL, Page id, subreddit, LinkedIn url, ...).
`POST /api/targets/sync` asks the Chrome extension to enumerate joined FB groups and
upserts them by (platform_id, external_id).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.db.models import Target
from app.platforms.facebook import FacebookPlatform
from app.schemas import TargetIn, TargetOut, TargetPatch

router = APIRouter(prefix="/api/targets", tags=["targets"])


@router.get("", response_model=list[TargetOut])
def list_targets(
    platform_id: str | None = None,
    active_only: bool = False,
    db: Session = Depends(get_session),
) -> list[Target]:
    q = db.query(Target)
    if platform_id:
        q = q.filter(Target.platform_id == platform_id)
    if active_only:
        q = q.filter(Target.active.is_(True))
    return q.order_by(Target.created_at.desc()).all()


@router.post("", response_model=TargetOut, status_code=status.HTTP_201_CREATED)
def create_target(payload: TargetIn, db: Session = Depends(get_session)) -> Target:
    existing = (
        db.query(Target)
        .filter(Target.platform_id == payload.platform_id)
        .filter(Target.external_id == payload.external_id)
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Target already exists with id={existing.id}",
        )
    target = Target(**payload.model_dump())
    db.add(target)
    db.commit()
    db.refresh(target)
    return target


@router.get("/{target_id}", response_model=TargetOut)
def get_target(target_id: int, db: Session = Depends(get_session)) -> Target:
    target = db.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")
    return target


@router.patch("/{target_id}", response_model=TargetOut)
def patch_target(
    target_id: int,
    payload: TargetPatch,
    db: Session = Depends(get_session),
) -> Target:
    target = db.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(target, key, value)
    db.commit()
    db.refresh(target)
    return target


@router.delete("/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_target(target_id: int, db: Session = Depends(get_session)) -> None:
    target = db.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")
    db.delete(target)
    db.commit()


@router.post("/sync", response_model=list[TargetOut])
async def sync_targets_from_extension(db: Session = Depends(get_session)) -> list[Target]:
    """Ask the connected Chrome extension to list joined FB groups, upsert them."""
    platform = FacebookPlatform()
    try:
        discovered = await platform.list_targets()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    result: list[Target] = []
    for item in discovered:
        existing = (
            db.query(Target)
            .filter(Target.platform_id == "facebook")
            .filter(Target.external_id == item["external_id"])
            .first()
        )
        if existing is None:
            target = Target(
                platform_id="facebook",
                external_id=item["external_id"],
                name=item["name"],
                member_count=item.get("member_count"),
                active=True,
            )
            db.add(target)
            result.append(target)
        else:
            existing.name = item["name"]
            if item.get("member_count") is not None:
                existing.member_count = item["member_count"]
            result.append(existing)

    db.commit()
    for t in result:
        db.refresh(t)
    return result
