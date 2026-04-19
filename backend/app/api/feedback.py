"""Feedback endpoint. Thumbs up/down on a post feeds into few-shot examples."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.db.models import Feedback, Post
from app.schemas import FeedbackIn, FeedbackOut

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


@router.post("", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
def create_feedback(payload: FeedbackIn, db: Session = Depends(get_session)) -> Feedback:
    if db.get(Post, payload.post_id) is None:
        raise HTTPException(status_code=404, detail="Post not found")
    row = Feedback(
        post_id=payload.post_id,
        rating=payload.rating,
        comment=payload.comment,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/by-post/{post_id}", response_model=list[FeedbackOut])
def list_feedback(post_id: int, db: Session = Depends(get_session)) -> list[Feedback]:
    return (
        db.query(Feedback)
        .filter(Feedback.post_id == post_id)
        .order_by(Feedback.created_at.desc())
        .all()
    )
