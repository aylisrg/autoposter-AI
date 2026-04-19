"""Target CRUD, discovery, AI scoring + clustering (M3).

Endpoints:
- CRUD: list/create/get/patch/delete
- POST /sync: enumerate joined FB groups via extension, upsert as source="scraped_joined"
- POST /discover: enumerate suggested FB groups via extension, upsert as
  source="scraped_suggested"
- POST /score: run TargetAgent over a batch (default: all unscored pending)
- POST /cluster: run TargetAgent clustering over approved targets, writes list_name
- POST /bulk-review: set review_status on many ids at once
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agents.targets import cluster_targets, score_targets
from app.db import get_session
from app.db.models import BusinessProfile, Target, TargetReviewStatus
from app.platforms.facebook import FacebookPlatform
from app.schemas import (
    TargetBulkReviewRequest,
    TargetClusterGroup,
    TargetClusterRequest,
    TargetClusterResponse,
    TargetDiscoverResult,
    TargetIn,
    TargetOut,
    TargetPatch,
    TargetScoreItem,
    TargetScoreRequest,
    TargetScoreResponse,
)
from app.ws.extension_bridge import bridge

log = logging.getLogger("api.targets")

router = APIRouter(prefix="/api/targets", tags=["targets"])


def _require_profile(db: Session) -> BusinessProfile:
    profile = db.query(BusinessProfile).first()
    if profile is None:
        raise HTTPException(
            status_code=400,
            detail="BusinessProfile is required — set it first via PUT /api/business-profile",
        )
    return profile


# ---------- CRUD ----------


@router.get("", response_model=list[TargetOut])
def list_targets(
    platform_id: str | None = None,
    active_only: bool = False,
    review_status: TargetReviewStatus | None = None,
    list_name: str | None = None,
    db: Session = Depends(get_session),
) -> list[Target]:
    q = db.query(Target)
    if platform_id:
        q = q.filter(Target.platform_id == platform_id)
    if active_only:
        q = q.filter(Target.active.is_(True))
    if review_status is not None:
        q = q.filter(Target.review_status == review_status)
    if list_name is not None:
        q = q.filter(Target.list_name == list_name)
    return q.order_by(Target.relevance_score.desc().nullslast(), Target.created_at.desc()).all()


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
    # Manually-added targets are approved by default.
    if payload.source == "manual":
        target.review_status = TargetReviewStatus.APPROVED
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


# ---------- Discovery via extension ----------


def _upsert_fb_targets(
    db: Session, discovered: list[dict], source: str
) -> tuple[list[Target], int, int]:
    """Upsert a batch of scraped FB groups. Returns (rows, created, updated)."""
    created = 0
    updated = 0
    rows: list[Target] = []
    for item in discovered:
        external_id = item.get("external_id") or item.get("url")
        if not external_id:
            continue
        existing = (
            db.query(Target)
            .filter(Target.platform_id == "facebook")
            .filter(Target.external_id == external_id)
            .first()
        )
        if existing is None:
            target = Target(
                platform_id="facebook",
                external_id=external_id,
                name=item.get("name", external_id),
                member_count=item.get("member_count"),
                description_snippet=item.get("description"),
                category=item.get("category"),
                active=True,
                source=source,
                review_status=(
                    TargetReviewStatus.APPROVED
                    if source == "scraped_joined"
                    else TargetReviewStatus.PENDING
                ),
            )
            db.add(target)
            rows.append(target)
            created += 1
        else:
            if item.get("name"):
                existing.name = item["name"]
            if item.get("member_count") is not None:
                existing.member_count = item["member_count"]
            if item.get("description"):
                existing.description_snippet = item["description"]
            if item.get("category"):
                existing.category = item["category"]
            rows.append(existing)
            updated += 1
    return rows, created, updated


@router.post("/sync", response_model=list[TargetOut])
async def sync_targets_from_extension(db: Session = Depends(get_session)) -> list[Target]:
    """List joined FB groups via extension, upsert with source=scraped_joined."""
    platform = FacebookPlatform()
    try:
        discovered = await platform.list_targets()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    rows, _, _ = _upsert_fb_targets(db, discovered, source="scraped_joined")
    db.commit()
    for t in rows:
        db.refresh(t)
    return rows


@router.post("/discover", response_model=TargetDiscoverResult)
async def discover_suggested_groups(db: Session = Depends(get_session)) -> TargetDiscoverResult:
    """Ask extension to scrape SUGGESTED groups (discovery feed). Inserts as pending."""
    request_id = uuid.uuid4().hex
    try:
        response = await bridge.request(
            {"type": "list_suggested_groups", "request_id": request_id}, timeout=60
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Extension timed out") from exc
    if not response.get("ok", True):
        raise HTTPException(
            status_code=502, detail=response.get("error", "Extension returned error")
        )
    discovered = response.get("groups", [])
    rows, created, updated = _upsert_fb_targets(db, discovered, source="scraped_suggested")
    db.commit()
    for t in rows:
        db.refresh(t)
    return TargetDiscoverResult(created=created, updated=updated, targets=rows)


# ---------- AI: score + cluster ----------


@router.post("/score", response_model=TargetScoreResponse)
def score_pending_targets(
    payload: TargetScoreRequest, db: Session = Depends(get_session)
) -> TargetScoreResponse:
    profile = _require_profile(db)
    q = db.query(Target)
    if payload.target_ids:
        q = q.filter(Target.id.in_(payload.target_ids))
    else:
        # Default: all pending targets that haven't been scored yet.
        q = q.filter(Target.review_status == TargetReviewStatus.PENDING)
        q = q.filter(Target.relevance_score.is_(None))
    targets = q.all()
    if not targets:
        return TargetScoreResponse(scored=[], cost_usd=0.0)

    try:
        result = score_targets(profile, targets)
    except Exception as exc:
        log.exception("TargetAgent.score_targets failed")
        raise HTTPException(status_code=502, detail=f"TargetAgent failed: {exc}") from exc

    by_id = {t.id: t for t in targets}
    out: list[TargetScoreItem] = []
    for s in result.scores:
        row = by_id.get(s.target_id)
        if row is None:
            continue
        row.relevance_score = s.score
        row.ai_reasoning = s.reasoning
        out.append(TargetScoreItem(target_id=s.target_id, score=s.score, reasoning=s.reasoning))
    db.commit()
    return TargetScoreResponse(scored=out, cost_usd=result.cost_usd)


@router.post("/cluster", response_model=TargetClusterResponse)
def cluster_approved_targets(
    payload: TargetClusterRequest, db: Session = Depends(get_session)
) -> TargetClusterResponse:
    profile = _require_profile(db)
    q = db.query(Target)
    if payload.target_ids:
        q = q.filter(Target.id.in_(payload.target_ids))
    else:
        q = q.filter(Target.review_status == TargetReviewStatus.APPROVED)
    targets = q.all()
    if not targets:
        return TargetClusterResponse(lists=[], cost_usd=0.0)

    try:
        result = cluster_targets(profile, targets)
    except Exception as exc:
        log.exception("TargetAgent.cluster_targets failed")
        raise HTTPException(status_code=502, detail=f"TargetAgent failed: {exc}") from exc

    by_id = {t.id: t for t in targets}
    for group in result.lists:
        for tid in group.target_ids:
            t = by_id.get(tid)
            if t is not None:
                t.list_name = group.list_name
    db.commit()
    return TargetClusterResponse(
        lists=[
            TargetClusterGroup(list_name=g.list_name, target_ids=g.target_ids)
            for g in result.lists
        ],
        cost_usd=result.cost_usd,
    )


@router.post("/bulk-review", response_model=list[TargetOut])
def bulk_review(
    payload: TargetBulkReviewRequest, db: Session = Depends(get_session)
) -> list[Target]:
    if not payload.target_ids:
        return []
    targets = db.query(Target).filter(Target.id.in_(payload.target_ids)).all()
    for t in targets:
        t.review_status = payload.review_status
    db.commit()
    for t in targets:
        db.refresh(t)
    return targets
