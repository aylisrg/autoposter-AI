"""Feedback endpoint. Thumbs up/down on a post feeds into few-shot examples."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.db.models import Feedback, Post
from app.schemas import FeedbackIn, FeedbackOut, FeedbackPatch

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


@router.get("/{feedback_id}", response_model=FeedbackOut)
def get_feedback(feedback_id: int, db: Session = Depends(get_session)) -> Feedback:
    row = db.get(Feedback, feedback_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return row


@router.patch("/{feedback_id}", response_model=FeedbackOut)
def patch_feedback(
    feedback_id: int,
    payload: FeedbackPatch,
    db: Session = Depends(get_session),
) -> Feedback:
    row = db.get(Feedback, feedback_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Feedback not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{feedback_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_feedback(feedback_id: int, db: Session = Depends(get_session)) -> None:
    row = db.get(Feedback, feedback_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Feedback not found")
    db.delete(row)
    db.commit()
