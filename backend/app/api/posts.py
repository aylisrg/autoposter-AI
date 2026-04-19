"""Post CRUD + generate + publish + schedule.

Core user-visible actions:
- POST /api/posts/generate — run Claude + (optionally) Gemini, return a draft.
- POST /api/posts/{id}/publish — publish now to the given target_ids.
- POST /api/posts/{id}/schedule — set scheduled_for; scheduler picks it up.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.ai.content import generate_post, generate_spintax_variant
from app.ai.image import generate_image
from app.db import get_session
from app.db.models import (
    BusinessProfile,
    Post,
    PostStatus,
    PostVariant,
    Target,
)
from app.platforms.facebook import FacebookPlatform
from app.schemas import (
    PostGenerate,
    PostIn,
    PostOut,
    PostPatch,
    PublishRequest,
    PublishResultOut,
)

log = logging.getLogger("api.posts")

router = APIRouter(prefix="/api/posts", tags=["posts"])


def _eager_load(db: Session, post_id: int) -> Post | None:
    return (
        db.query(Post)
        .options(selectinload(Post.variants))
        .filter(Post.id == post_id)
        .first()
    )


@router.get("", response_model=list[PostOut])
def list_posts(
    status_filter: PostStatus | None = None,
    limit: int = 100,
    db: Session = Depends(get_session),
) -> list[Post]:
    q = db.query(Post).options(selectinload(Post.variants))
    if status_filter is not None:
        q = q.filter(Post.status == status_filter)
    return q.order_by(Post.created_at.desc()).limit(limit).all()


@router.get("/{post_id}", response_model=PostOut)
def get_post(post_id: int, db: Session = Depends(get_session)) -> Post:
    post = _eager_load(db, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.post("", response_model=PostOut, status_code=status.HTTP_201_CREATED)
def create_post(payload: PostIn, db: Session = Depends(get_session)) -> Post:
    post = Post(**payload.model_dump(), status=PostStatus.DRAFT)
    db.add(post)
    db.commit()
    post = _eager_load(db, post.id)
    assert post is not None
    return post


@router.patch("/{post_id}", response_model=PostOut)
def patch_post(
    post_id: int,
    payload: PostPatch,
    db: Session = Depends(get_session),
) -> Post:
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(post, key, value)
    db.commit()
    refreshed = _eager_load(db, post.id)
    assert refreshed is not None
    return refreshed


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(post_id: int, db: Session = Depends(get_session)) -> None:
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    db.delete(post)
    db.commit()


@router.post("/generate", response_model=PostOut, status_code=status.HTTP_201_CREATED)
def generate(
    payload: PostGenerate,
    db: Session = Depends(get_session),
) -> Post:
    profile = db.query(BusinessProfile).order_by(BusinessProfile.id.asc()).first()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Business profile must be set before generating posts.",
        )

    generated = generate_post(
        db=db,
        post_type=payload.post_type,
        business_profile=profile,
        topic_hint=payload.topic_hint,
        use_few_shot=payload.use_few_shot,
    )

    image_url: str | None = None
    image_prompt: str | None = None
    total_cost = generated.cost_usd
    if payload.generate_image:
        img = generate_image(
            post_text=generated.text,
            business_desc=profile.description,
            tone=profile.tone.value,
        )
        image_url = f"/static/{img.local_path}"
        image_prompt = img.prompt
        total_cost += img.cost_usd

    post = Post(
        post_type=payload.post_type,
        status=PostStatus.DRAFT,
        text=generated.text,
        image_url=image_url,
        image_prompt=image_prompt,
        generation_prompt=generated.user_prompt,
        generation_model=generated.model,
        generation_cost_usd=total_cost,
    )
    db.add(post)
    db.commit()
    refreshed = _eager_load(db, post.id)
    assert refreshed is not None
    return refreshed


def _ensure_variants(
    db: Session,
    post: Post,
    target_ids: list[int],
    profile: BusinessProfile | None,
    generate_spintax: bool,
) -> list[PostVariant]:
    """Create PostVariant rows for each target if they don't exist yet.

    First target uses the main post text as-is. Others get a spintaxed rewrite IF
    `generate_spintax` is true AND we have a business profile AND an ANTHROPIC key.
    On spintax failure we fall back to the original text (logged).
    """
    existing = {v.target_id: v for v in post.variants}
    targets: list[Target] = [t for t in (db.get(Target, tid) for tid in target_ids) if t is not None]
    if not targets:
        raise HTTPException(status_code=400, detail="No valid targets provided.")

    out: list[PostVariant] = []
    for idx, target in enumerate(targets):
        if target.id in existing:
            out.append(existing[target.id])
            continue
        if idx == 0 or not generate_spintax or profile is None:
            text = post.text
        else:
            try:
                text = generate_spintax_variant(post.text, profile)
            except Exception as exc:
                log.warning("Spintax failed for target %s: %s — using original", target.id, exc)
                text = post.text
        variant = PostVariant(
            post_id=post.id,
            target_id=target.id,
            text=text,
            status=PostStatus.SCHEDULED,
            scheduled_for=post.scheduled_for,
        )
        db.add(variant)
        out.append(variant)
    db.commit()
    return out


async def _publish_variant(post: Post, variant: PostVariant, target: Target) -> None:
    """Dispatch one variant through the Facebook platform. Mutates `variant`."""
    platform = FacebookPlatform()
    variant.status = PostStatus.POSTING
    try:
        synthetic_post = Post(
            id=post.id,
            post_type=post.post_type,
            status=PostStatus.POSTING,
            text=variant.text,
            image_url=post.image_url,
            first_comment=post.first_comment,
            cta_url=post.cta_url,
        )
        result = await platform.publish(synthetic_post, target)
    except Exception as exc:
        variant.status = PostStatus.FAILED
        variant.error = f"Exception: {exc}"
        return

    if result.ok:
        variant.status = PostStatus.POSTED
        variant.external_post_id = result.external_post_id
        variant.posted_at = datetime.now(UTC)
        variant.error = None
    else:
        variant.status = PostStatus.FAILED
        variant.error = result.error


@router.post("/{post_id}/publish", response_model=PublishResultOut)
async def publish_now(
    post_id: int,
    payload: PublishRequest,
    db: Session = Depends(get_session),
) -> PublishResultOut:
    post = _eager_load(db, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    target_ids = payload.target_ids
    if not target_ids:
        active = db.query(Target).filter(Target.active.is_(True)).all()
        target_ids = [t.id for t in active]
        if not target_ids:
            raise HTTPException(status_code=400, detail="No active targets. Add some first.")

    profile = db.query(BusinessProfile).order_by(BusinessProfile.id.asc()).first()

    variants = _ensure_variants(
        db,
        post,
        target_ids=target_ids,
        profile=profile,
        generate_spintax=payload.generate_spintax,
    )

    post.status = PostStatus.POSTING
    db.commit()

    for variant in variants:
        target = db.get(Target, variant.target_id)
        if target is None:
            variant.status = PostStatus.FAILED
            variant.error = "Target row vanished between enqueue and publish."
            continue
        await _publish_variant(post, variant, target)
        db.commit()

    any_ok = any(v.status == PostStatus.POSTED for v in variants)
    all_ok = all(v.status == PostStatus.POSTED for v in variants)
    if all_ok:
        post.status = PostStatus.POSTED
        post.posted_at = datetime.now(UTC)
    elif any_ok:
        post.status = PostStatus.POSTED
        post.posted_at = datetime.now(UTC)
    else:
        post.status = PostStatus.FAILED
    db.commit()

    refreshed = _eager_load(db, post.id)
    assert refreshed is not None
    return PublishResultOut(
        post_id=refreshed.id,
        status=refreshed.status,
        variants=refreshed.variants,  # type: ignore[arg-type]
    )


@router.post("/{post_id}/schedule", response_model=PostOut)
def schedule(
    post_id: int,
    payload: PublishRequest,
    db: Session = Depends(get_session),
) -> Post:
    if payload.scheduled_for is None:
        raise HTTPException(
            status_code=400,
            detail="scheduled_for is required for /schedule. Use /publish for immediate.",
        )

    post = _eager_load(db, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    target_ids = payload.target_ids
    if not target_ids:
        active = db.query(Target).filter(Target.active.is_(True)).all()
        target_ids = [t.id for t in active]
        if not target_ids:
            raise HTTPException(status_code=400, detail="No active targets. Add some first.")

    post.scheduled_for = payload.scheduled_for
    profile = db.query(BusinessProfile).order_by(BusinessProfile.id.asc()).first()
    _ensure_variants(
        db,
        post,
        target_ids=target_ids,
        profile=profile,
        generate_spintax=payload.generate_spintax,
    )
    post.status = PostStatus.SCHEDULED
    db.commit()

    refreshed = _eager_load(db, post.id)
    assert refreshed is not None
    return refreshed


