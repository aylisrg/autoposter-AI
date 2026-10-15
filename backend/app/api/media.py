"""Media library endpoints.

POST   /api/media/upload                  — upload image, store on disk + DB
GET    /api/media                         — list assets
GET    /api/media/{id}                    — detail
PATCH  /api/media/{id}                    — edit user tags
DELETE /api/media/{id}
POST   /api/media/{id}/tag                — (re)run Claude Vision tagging
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
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from PIL import Image as PILImage
from sqlalchemy.orm import Session

from app.ai.vision import media_relevance_score, tag_image
from app.media.tagging import tag_and_embed_asset
from app.db import get_session
from app.db.models import MediaAsset, MediaKind, PlanSlot
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

ALLOWED_MIME = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}
EXT_MAP = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_BYTES_IMAGE = 10 * 1024 * 1024  # 10 MB for images
MAX_BYTES_VIDEO = 500 * 1024 * 1024  # 500 MB for videos


def _read_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        with PILImage.open(path) as img:
            return int(img.width), int(img.height)
    except Exception as exc:  # noqa: BLE001
        log.warning("Pillow failed to open %s: %s", path, exc)
        return None, None


@router.post("/upload", response_model=MediaUploadOut)
async def upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
) -> MediaUploadOut:
    mime = file.content_type or "application/octet-stream"
    if mime not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail=f"Unsupported mime type: {mime}")

    data = await file.read()
    if len(data) > MAX_BYTES_IMAGE:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    ext = EXT_MAP[mime]
    filename = f"{uuid.uuid4().hex}{ext}"
    out_path = UPLOADS_DIR / filename
    out_path.write_bytes(data)
    width, height = _read_dimensions(out_path)

    asset = MediaAsset(
        kind=MediaKind.IMAGE,
        mime=mime,
        local_path=f"images/uploads/{filename}",
        filename=filename,
        size_bytes=len(data),
        width=width,
        height=height,
        ai_caption=None,
        ai_tags=[],
        tags_user=[],
        variants_json={},
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    # Async AI tagging + embedding (Claude Vision + local embed)
    background_tasks.add_task(tag_and_embed_asset, asset.id)

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
    from app.media.tagging import compute_local_embedding
    text_for_embed = f"{result.caption} {' '.join(result.tags)}"
    asset.embedding = compute_local_embedding(text_for_embed)
    asset.tagged_at = datetime.now(UTC)
    db.commit()
    db.refresh(asset)
    return MediaTagResult(caption=result.caption, tags=result.tags, cost_usd=result.cost_usd)


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


# --- TUS resumable upload for videos (issue #20) ---

from fastapi import Header, Request
from fastapi.responses import Response

# In-memory metadata for active TUS uploads (offset derived from file size)
_tus_meta: dict[str, dict] = {}


def _tus_path(upload_id: str) -> Path:
    tus_dir = UPLOADS_DIR / "tus"
    tus_dir.mkdir(parents=True, exist_ok=True)
    return tus_dir / upload_id


@router.post("/tus", status_code=201)
async def tus_create(
    request: Request,
    upload_length: int = Header(..., alias="Upload-Length"),
    upload_metadata: str | None = Header(None, alias="Upload-Metadata"),
    db: Session = Depends(get_session),
) -> Response:
    """TUS creation: start a resumable upload (videos)."""
    if upload_length > MAX_BYTES_VIDEO:
        raise HTTPException(status_code=413, detail="File too large (max 500 MB)")
    if upload_length <= 0:
        raise HTTPException(status_code=400, detail="Invalid Upload-Length")

    upload_id = uuid.uuid4().hex
    path = _tus_path(upload_id)
    path.touch()

    # Parse metadata for filename/mime if present (base64 key value pairs)
    mime = "video/mp4"
    filename = f"{upload_id}.mp4"
    if upload_metadata:
        # Simple parse: "filename base64,filetype base64"
        try:
            parts = upload_metadata.split(",")
            for p in parts:
                if " " in p:
                    key, val = p.strip().split(" ", 1)
                    if key == "filetype":
                        import base64
                        mime = base64.b64decode(val).decode()
                    if key == "filename":
                        import base64
                        filename = base64.b64decode(val).decode()
        except Exception:
            pass

    _tus_meta[upload_id] = {
        "length": upload_length,
        "mime": mime,
        "filename": filename,
        "offset": 0,
    }

    location = str(request.url_for("tus_patch", upload_id=upload_id))
    return Response(
        status_code=201,
        headers={
            "Location": location,
            "Tus-Resumable": "1.0.0",
            "Upload-Offset": "0",
        },
    )


@router.head("/tus/{upload_id}")
async def tus_head(upload_id: str) -> Response:
    """TUS HEAD: return current offset."""
    meta = _tus_meta.get(upload_id)
    path = _tus_path(upload_id)
    if not meta or not path.exists():
        raise HTTPException(status_code=404, detail="Upload not found")
    offset = path.stat().st_size
    return Response(
        status_code=200,
        headers={
            "Upload-Offset": str(offset),
            "Upload-Length": str(meta["length"]),
            "Tus-Resumable": "1.0.0",
            "Cache-Control": "no-store",
        },
    )


@router.patch("/tus/{upload_id}")
async def tus_patch(
    upload_id: str,
    request: Request,
    upload_offset: int = Header(..., alias="Upload-Offset"),
    db: Session = Depends(get_session),
) -> Response:
    """TUS PATCH: append chunk at offset. Completes the asset when done."""
    meta = _tus_meta.get(upload_id)
    path = _tus_path(upload_id)
    if not meta or not path.exists():
        raise HTTPException(status_code=404, detail="Upload not found")

    current = path.stat().st_size
    if upload_offset != current:
        raise HTTPException(status_code=409, detail="Offset mismatch")

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty patch")

    new_offset = current + len(body)
    if new_offset > meta["length"]:
        raise HTTPException(status_code=413, detail="Exceeds declared length")

    with path.open("ab") as f:
        f.write(body)

    headers = {
        "Upload-Offset": str(new_offset),
        "Tus-Resumable": "1.0.0",
    }

    if new_offset == meta["length"]:
        # Complete: move to final location and create MediaAsset
        final_name = f"{uuid.uuid4().hex}_{meta['filename']}"
        final_path = UPLOADS_DIR / final_name
        path.rename(final_path)
        del _tus_meta[upload_id]

        asset = MediaAsset(
            kind=MediaKind.VIDEO,
            mime=meta["mime"],
            local_path=f"images/uploads/{final_name}",
            filename=final_name,
            size_bytes=new_offset,
            width=None,
            height=None,
            duration_sec=None,
            ai_tags=[],
            tags_user=[],
            variants_json={},
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        headers["Upload-Complete"] = "1"
        # Could return the asset id, but TUS typically just 204
        return Response(status_code=204, headers=headers)

    return Response(status_code=204, headers=headers)


# Support simple full POST for photos already exists at /upload.
# Videos are expected to use the TUS flow above.
