"""Health + status endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
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


@router.post("/api/extension/smoke")
async def extension_smoke() -> dict:
    """Run the FB content-script smoke test through the WebSocket bridge.

    Lets the dashboard surface "selectors healthy?" without needing DevTools.
    The extension must be connected AND on a facebook.com tab for this to
    produce a useful report.
    """
    if not bridge.connected:
        raise HTTPException(
            status_code=503,
            detail="Extension not connected. Load the extension and open facebook.com.",
        )
    try:
        response = await bridge.request(
            {"type": "smoke", "request_id": uuid.uuid4().hex},
            timeout=30,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="Extension did not respond within 30s (no FB tab open?)",
        ) from exc
    if not response.get("ok"):
        raise HTTPException(
            status_code=502,
            detail=response.get("error", "Extension reported failure"),
        )
    return {"ok": True, "report": response.get("report", {})}
