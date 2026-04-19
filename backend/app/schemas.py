"""Pydantic schemas for REST API I/O.

Naming: `FooIn` = request body, `FooOut` = response body, `FooPatch` = partial update.
We deliberately don't use SQLAlchemy models in responses — the API surface should
be independently versioned from the DB schema.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import (
    EmojiDensity,
    FeedbackRating,
    Length,
    PostStatus,
    PostType,
    Tone,
)

# ---------- BusinessProfile ----------


class BusinessProfileIn(BaseModel):
    name: str
    description: str
    website_url: str | None = None
    products: str | None = None
    target_audience: str | None = None
    call_to_action_url: str | None = None

    tone: Tone = Tone.CASUAL
    length: Length = Length.MEDIUM
    emoji_density: EmojiDensity = EmojiDensity.LIGHT
    language: str = "en"

    post_type_ratios: dict = Field(default_factory=dict)
    posting_window_start_hour: int = 9
    posting_window_end_hour: int = 20
    timezone: str = "UTC"
    posts_per_day: int = 3
    review_before_posting: bool = True


class BusinessProfileOut(BusinessProfileIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


# ---------- Target ----------


class TargetIn(BaseModel):
    platform_id: str = "facebook"
    external_id: str
    name: str
    tags: list[str] = Field(default_factory=list)
    list_name: str | None = None
    member_count: int | None = None
    active: bool = True


class TargetPatch(BaseModel):
    name: str | None = None
    tags: list[str] | None = None
    list_name: str | None = None
    member_count: int | None = None
    active: bool | None = None


class TargetOut(TargetIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


# ---------- Post ----------


class PostIn(BaseModel):
    post_type: PostType
    text: str
    image_url: str | None = None
    image_prompt: str | None = None
    first_comment: str | None = None
    cta_url: str | None = None
    scheduled_for: datetime | None = None


class PostPatch(BaseModel):
    post_type: PostType | None = None
    status: PostStatus | None = None
    text: str | None = None
    image_url: str | None = None
    image_prompt: str | None = None
    first_comment: str | None = None
    cta_url: str | None = None
    scheduled_for: datetime | None = None


class PostGenerate(BaseModel):
    post_type: PostType
    topic_hint: str | None = None
    generate_image: bool = False
    use_few_shot: bool = True


class PostVariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    post_id: int
    target_id: int
    text: str
    status: PostStatus
    scheduled_for: datetime | None
    posted_at: datetime | None
    external_post_id: str | None
    error: str | None


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    post_type: PostType
    status: PostStatus
    text: str
    image_url: str | None
    image_prompt: str | None
    first_comment: str | None
    cta_url: str | None
    scheduled_for: datetime | None
    posted_at: datetime | None
    generation_model: str | None
    generation_cost_usd: float | None
    created_at: datetime
    variants: list[PostVariantOut] = Field(default_factory=list)


class PublishRequest(BaseModel):
    """Payload for POST /api/posts/{id}/publish and /schedule.

    `target_ids` — which Target rows to post to. If empty, use all active targets
    matching the post's platform. For /schedule, `scheduled_for` is required.
    """

    target_ids: list[int] = Field(default_factory=list)
    scheduled_for: datetime | None = None
    generate_spintax: bool = True


class PublishResultOut(BaseModel):
    post_id: int
    status: PostStatus
    variants: list[PostVariantOut]


# ---------- Feedback ----------


class FeedbackIn(BaseModel):
    post_id: int
    rating: FeedbackRating
    comment: str | None = None


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    post_id: int
    rating: FeedbackRating
    comment: str | None
    created_at: datetime


# ---------- Media ----------


class MediaUploadOut(BaseModel):
    """Returned after a successful /api/media/upload."""

    url: str  # relative to backend root, e.g. "/static/images/uploads/abc.png"
    filename: str
    mime: str
    size_bytes: int


# ---------- Status ----------


class StatusOut(BaseModel):
    ok: bool
    version: str
    extension_connected: bool
    scheduler_running: bool
    next_scheduled_post_at: datetime | None
    pending_posts: int
