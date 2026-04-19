"""Health + status endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.db.models import Post, PostStatus
from app.schemas import StatusOut
from app.ws.extension_bridge import bridge

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict:
    """Lightweight liveness check — no DB hit."""
    return {
        "ok": True,
        "extension_connected": bridge.connected,
        "version": "0.1.0",
    }


@router.get("/api/status", response_model=StatusOut)
def status(db: Session = Depends(get_session)) -> StatusOut:
    from app.scheduler import scheduler  # late import to avoid cycles

    next_post = (
        db.query(Post)
        .filter(Post.status == PostStatus.SCHEDULED)
        .filter(Post.scheduled_for.isnot(None))
        .order_by(Post.scheduled_for.asc())
        .first()
    )
    pending = (
        db.query(Post).filter(Post.status.in_([PostStatus.SCHEDULED, PostStatus.DRAFT])).count()
    )

    return StatusOut(
        ok=True,
        version="0.1.0",
        extension_connected=bridge.connected,
        scheduler_running=scheduler.is_running(),
        next_scheduled_post_at=next_post.scheduled_for if next_post else None,
        pending_posts=pending,
    )


@router.post("/api/admin/backup")
def run_backup_now() -> dict:
    """Trigger an on-demand backup (the scheduler also runs one at 03:00 UTC)."""
    from app.services import backups

    path = backups.run_backup()
    return {"ok": True, "path": str(path), "size_bytes": path.stat().st_size}
