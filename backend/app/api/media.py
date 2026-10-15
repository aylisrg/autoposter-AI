"""Media library endpoints.

POST   /api/media/upload                  — upload image/video, store on disk + DB
GET    /api/media                         — list assets
GET    /api/media/{id}                    — detail
PATCH  /api/media/{id}                    — edit user tags
DELETE /api/media/{id}
POST   /api/media/{id}/tag                — (re)run Claude Vision tagging
POST   /api/media/{id}/transcode          — generate IG/Threads video variants (#22)
POST   /api/media/{id}/attach-to-slot/{slot_id}
                                          — link asset to a PlanSlot
GET    /api/media/suggest-for-slot/{slot_id}?limit=3
                                          — top-N by tag overlap
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from PIL import Image as PILImage
from sqlalchemy.orm import Session

from app.ai.vision import media_relevance_score, tag_image
from app.db import get_session
from app.db.models import MediaAsset, MediaKind, PlanSlot
from app.media.transcode import TranscodeError, probe, transcode_all
from app.schemas import (
    MediaAssetOut,
    MediaAssetPatch,
    MediaSuggestion,
    MediaTagResult,
    MediaUploadOut,
)

log = logging.getLogger("api.media")
router = APIRouter(prefix="/api/media", tags=["media"])

UPLOADS_DIR = Path("data/images/uploads")
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_UPLOADS_DIR = Path("data/media/uploads")
VIDEO_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_MIME = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}
ALLOWED_VIDEO_MIME = {
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "video/x-msvideo",
}
ALLOWED_MIME = ALLOWED_IMAGE_MIME | ALLOWED_VIDEO_MIME
EXT_MAP = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/x-msvideo": ".avi",
}
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_VIDEO_BYTES = 200 * 1024 * 1024  # 200 MB for v1


def _read_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        with PILImage.open(path) as img:
            return int(img.width), int(img.height)
    except Exception as exc:  # noqa: BLE001
        log.warning("Pillow failed to open %s: %s", path, exc)
        return None, None


@router.post("/upload", response_model=MediaUploadOut)
async def upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
) -> MediaUploadOut:
    mime = file.content_type or "application/octet-stream"
    if mime not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail=f"Unsupported mime type: {mime}")

    data = await file.read()
    is_video = mime in ALLOWED_VIDEO_MIME
    max_bytes = MAX_VIDEO_BYTES if is_video else MAX_IMAGE_BYTES
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {max_bytes // (1024 * 1024)} MB)",
        )
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    ext = EXT_MAP[mime]
    filename = f"{uuid.uuid4().hex}{ext}"
    if is_video:
        out_dir = VIDEO_UPLOADS_DIR
        local_prefix = "media/uploads"
        kind = MediaKind.VIDEO
    else:
        out_dir = UPLOADS_DIR
        local_prefix = "images/uploads"
        kind = MediaKind.IMAGE
    out_path = out_dir / filename
    out_path.write_bytes(data)

    width: int | None = None
    height: int | None = None
    duration_sec: float | None = None
    if is_video:
        try:
            info = probe(out_path)
            width, height = info.width, info.height
            duration_sec = info.duration
        except TranscodeError as exc:
            log.warning("ffprobe failed on upload %s: %s", out_path, exc)
    else:
        width, height = _read_dimensions(out_path)

    asset = MediaAsset(
        kind=kind,
        mime=mime,
        local_path=f"{local_prefix}/{filename}",
        filename=filename,
        size_bytes=len(data),
        width=width,
        height=height,
        duration_sec=duration_sec,
        ai_caption=None,
        ai_tags=[],
        tags_user=[],
        variants_json={},
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    return MediaUploadOut(
        id=asset.id,
        url=f"/static/{asset.local_path}",
        filename=asset.filename,
        mime=asset.mime,
        size_bytes=asset.size_bytes,
        width=asset.width,
        height=asset.height,
    )


@router.get("", response_model=list[MediaAssetOut])
def list_media(
    limit: int = 200,
    db: Session = Depends(get_session),
) -> list[MediaAsset]:
    return (
        db.query(MediaAsset)
        .order_by(MediaAsset.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/{asset_id}", response_model=MediaAssetOut)
def get_media(asset_id: int, db: Session = Depends(get_session)) -> MediaAsset:
    asset = db.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


@router.patch("/{asset_id}", response_model=MediaAssetOut)
def patch_media(
    asset_id: int,
    payload: MediaAssetPatch,
    db: Session = Depends(get_session),
) -> MediaAsset:
    asset = db.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(asset, key, value)
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_media(asset_id: int, db: Session = Depends(get_session)) -> None:
    asset = db.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    # Best-effort: remove file. We don't fail the API call if the file is already gone.
    full_path = Path("data") / asset.local_path
    try:
        if full_path.exists():
            full_path.unlink()
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not remove %s: %s", full_path, exc)
    # Also remove known variants
    for rel in (asset.variants_json or {}).values():
        try:
            vpath = Path("data") / str(rel)
            if vpath.exists():
                vpath.unlink()
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not remove variant %s: %s", rel, exc)
    db.delete(asset)
    db.commit()


@router.post("/{asset_id}/tag", response_model=MediaTagResult)
def run_tagging(asset_id: int, db: Session = Depends(get_session)) -> MediaTagResult:
    asset = db.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    full_path = Path("data") / asset.local_path
    if not full_path.exists():
        raise HTTPException(status_code=410, detail="Underlying file missing")

    result = tag_image(full_path, mime=asset.mime)
    asset.ai_caption = result.caption
    asset.ai_tags = result.tags
    asset.tagged_at = datetime.now(UTC)
    db.commit()
    db.refresh(asset)
    return MediaTagResult(caption=result.caption, tags=result.tags, cost_usd=result.cost_usd)


@router.post("/{asset_id}/transcode", response_model=MediaAssetOut)
def run_transcode(
    asset_id: int,
    db: Session = Depends(get_session),
) -> MediaAsset:
    """Generate IG/Threads aspect variants for a video MediaAsset (#22)."""
    asset = db.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset.kind != MediaKind.VIDEO:
        raise HTTPException(
            status_code=400,
            detail="Transcode only applies to video assets",
        )
    full_path = Path("data") / asset.local_path
    if not full_path.exists():
        raise HTTPException(status_code=410, detail="Underlying file missing")

    try:
        variants = transcode_all(full_path)
    except TranscodeError as exc:
        log.exception("transcode failed for asset %s", asset_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Merge with any existing variants (idempotent re-run replaces keys)
    existing = dict(asset.variants_json or {})
    existing.update(variants)
    asset.variants_json = existing
    # Refresh dimensions from source if still missing
    if asset.width is None or asset.height is None:
        try:
            info = probe(full_path)
            asset.width = info.width
            asset.height = info.height
            asset.duration_sec = info.duration
        except TranscodeError:
            pass
    db.commit()
    db.refresh(asset)
    return asset


@router.post(
    "/{asset_id}/attach-to-slot/{slot_id}",
    response_model=MediaAssetOut,
)
def attach_to_slot(
    asset_id: int,
    slot_id: int,
    db: Session = Depends(get_session),
) -> MediaAsset:
    asset = db.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    slot = db.get(PlanSlot, slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="Slot not found")
    slot.media_asset_id = asset.id
    db.commit()
    return asset


@router.get(
    "/suggest-for-slot/{slot_id}",
    response_model=list[MediaSuggestion],
)
def suggest_for_slot(
    slot_id: int,
    limit: int = 3,
    db: Session = Depends(get_session),
) -> list[MediaSuggestion]:
    slot = db.get(PlanSlot, slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="Slot not found")
    assets = db.query(MediaAsset).all()
    scored: list[tuple[float, MediaAsset]] = []
    for a in assets:
        score = media_relevance_score(
            slot_post_type=slot.post_type.value,
            slot_topic_hint=slot.topic_hint,
            asset_tags=a.ai_tags or [],
            asset_caption=a.ai_caption,
        )
        if score > 0:
            scored.append((score, a))
    scored.sort(key=lambda t: t[0], reverse=True)
    out: list[MediaSuggestion] = []
    for score, a in scored[:limit]:
        out.append(
            MediaSuggestion(
                asset=MediaAssetOut.model_validate(a),
                score=round(score, 4),
            )
        )
    return out
