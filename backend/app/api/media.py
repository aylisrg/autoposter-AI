"""Media upload endpoint. User drops a photo, we save it under data/images/uploads/
and return a URL the frontend can embed / hand to the extension."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.schemas import MediaUploadOut

router = APIRouter(prefix="/api/media", tags=["media"])

UPLOADS_DIR = Path("data/images/uploads")
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_MIME = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}
MAX_BYTES = 10 * 1024 * 1024  # 10 MB for v1 — images only


@router.post("/upload", response_model=MediaUploadOut)
async def upload(file: UploadFile = File(...)) -> MediaUploadOut:
    mime = file.content_type or "application/octet-stream"
    if mime not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail=f"Unsupported mime type: {mime}")

    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    ext_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    ext = ext_map[mime]
    filename = f"{uuid.uuid4().hex}{ext}"
    out_path = UPLOADS_DIR / filename
    out_path.write_bytes(data)

    return MediaUploadOut(
        url=f"/static/images/uploads/{filename}",
        filename=filename,
        mime=mime,
        size_bytes=len(data),
    )
