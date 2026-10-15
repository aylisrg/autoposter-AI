"""Review queue endpoints (M5).

Separate from the post-status based review flow so that review decisions,
edits and bulk actions can be tracked independently of the Post lifecycle.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.db.models import Post, ReviewQueueItem, ReviewQueueStatus
from app.schemas import (
    ReviewQueueBulkApproveRequest,
    ReviewQueueEditRequest,
    ReviewQueueItemOut,
)

router = APIRouter(prefix="/api/review", tags=["review"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("", response_model=list[ReviewQueueItemOut])
def list_review_queue(
    status_filter: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_session),
) -> list[ReviewQueueItem]:
    q = db.query(ReviewQueueItem)
    if status_filter:
        try:
            st = ReviewQueueStatus(status_filter)
            q = q.filter(ReviewQueueItem.status == st)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown status {status_filter}")
    return (
        q.order_by(ReviewQueueItem.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.post("/{item_id}/approve", response_model=ReviewQueueItemOut)
def approve_item(item_id: int, db: Session = Depends(get_session)) -> ReviewQueueItem:
    item = db.get(ReviewQueueItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    if item.status != ReviewQueueStatus.PENDING:
        raise HTTPException(status_code=400, detail="Only pending items can be approved")
    item.status = ReviewQueueStatus.APPROVED
    item.reviewed_at = _utcnow()
    item.reviewer_action = {"action": "approve"}
    # Move the post out of pending_review if it is still there
    post = db.get(Post, item.post_id)
    if post and post.status.value == "pending_review":
        post.status = "draft"  # type: ignore[assignment]
    db.commit()
    db.refresh(item)
    return item


@router.post("/{item_id}/edit", response_model=ReviewQueueItemOut)
def edit_item(
    item_id: int,
    payload: ReviewQueueEditRequest,
    db: Session = Depends(get_session),
) -> ReviewQueueItem:
    item = db.get(ReviewQueueItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    post = db.get(Post, item.post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    changes: dict = {}
    if payload.text is not None:
        post.text = payload.text
        changes["text"] = payload.text
    if payload.media_asset_id is not None:
        post.media_asset_id = payload.media_asset_id
        changes["media_asset_id"] = payload.media_asset_id
    if payload.image_url is not None:
        post.image_url = payload.image_url
        changes["image_url"] = payload.image_url
    item.status = ReviewQueueStatus.EDITED
    item.reviewed_at = _utcnow()
    item.reviewer_action = {"action": "edit", "changes": changes}
    if post.status.value == "pending_review":
        post.status = "draft"  # type: ignore[assignment]
    db.commit()
    db.refresh(item)
    return item


@router.post("/{item_id}/reject", response_model=ReviewQueueItemOut)
def reject_item(item_id: int, db: Session = Depends(get_session)) -> ReviewQueueItem:
    item = db.get(ReviewQueueItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    if item.status != ReviewQueueStatus.PENDING:
        raise HTTPException(status_code=400, detail="Only pending items can be rejected")
    item.status = ReviewQueueStatus.REJECTED
    item.reviewed_at = _utcnow()
    item.reviewer_action = {"action": "reject"}
    post = db.get(Post, item.post_id)
    if post and post.status.value == "pending_review":
        post.status = "skipped"  # type: ignore[assignment]
    db.commit()
    db.refresh(item)
    return item


@router.post("/bulk_approve", response_model=list[ReviewQueueItemOut])
def bulk_approve(
    payload: ReviewQueueBulkApproveRequest,
    db: Session = Depends(get_session),
) -> list[ReviewQueueItem]:
    if not payload.ids:
        raise HTTPException(status_code=400, detail="No ids provided")
    items = (
        db.query(ReviewQueueItem)
        .filter(ReviewQueueItem.id.in_(payload.ids))
        .all()
    )
    approved: list[ReviewQueueItem] = []
    now = _utcnow()
    for item in items:
        if item.status != ReviewQueueStatus.PENDING:
            continue
        item.status = ReviewQueueStatus.APPROVED
        item.reviewed_at = now
        item.reviewer_action = {"action": "bulk_approve"}
        post = db.get(Post, item.post_id)
        if post and post.status.value == "pending_review":
            post.status = "draft"  # type: ignore[assignment]
        approved.append(item)
    db.commit()
    for item in approved:
        db.refresh(item)
    return approved
