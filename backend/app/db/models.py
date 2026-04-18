"""SQLAlchemy models for the whole app.

Design notes:
- Everything related to a single user for v1 (personal use) — no user_id columns yet.
  Added in Etap 6 if we go multi-tenant.
- BusinessProfile is a singleton for v1. In future: one per user/project.
- Post has a lifecycle: draft -> scheduled -> posting -> posted / failed / skipped.
- PostVariant is per-target (per-group) spintax variation.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------- Enums ----------


class PostType(str, enum.Enum):
    INFORMATIVE = "informative"
    SOFT_SELL = "soft_sell"
    HARD_SELL = "hard_sell"
    ENGAGEMENT = "engagement"
    STORY = "story"
    MOTIVATIONAL = "motivational"
    TESTIMONIAL = "testimonial"
    HOT_TAKE = "hot_take"
    SEASONAL = "seasonal"


class PostStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    SCHEDULED = "scheduled"
    POSTING = "posting"
    POSTED = "posted"
    FAILED = "failed"
    SKIPPED = "skipped"


class Tone(str, enum.Enum):
    PROFESSIONAL = "professional"
    CASUAL = "casual"
    FUN = "fun"


class Length(str, enum.Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class EmojiDensity(str, enum.Enum):
    NONE = "none"
    LIGHT = "light"
    MEDIUM = "medium"
    HEAVY = "heavy"


class FeedbackRating(str, enum.Enum):
    UP = "up"
    DOWN = "down"


# ---------- Models ----------


class BusinessProfile(Base):
    """The user's business voice and context. Single row for v1."""
    __tablename__ = "business_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    products: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    call_to_action_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Voice controls
    tone: Mapped[Tone] = mapped_column(Enum(Tone), default=Tone.CASUAL)
    length: Mapped[Length] = mapped_column(Enum(Length), default=Length.MEDIUM)
    emoji_density: Mapped[EmojiDensity] = mapped_column(
        Enum(EmojiDensity), default=EmojiDensity.LIGHT
    )
    language: Mapped[str] = mapped_column(String(10), default="en")

    # Posting preferences (JSON blob: ratios of 9 post types, posting windows, etc.)
    post_type_ratios: Mapped[dict] = mapped_column(JSON, default=dict)
    posting_window_start_hour: Mapped[int] = mapped_column(Integer, default=9)
    posting_window_end_hour: Mapped[int] = mapped_column(Integer, default=20)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")
    posts_per_day: Mapped[int] = mapped_column(Integer, default=3)
    review_before_posting: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Target(Base):
    """A place to post to: FB group, FB page, LinkedIn profile, X account, subreddit, etc.

    Platform-agnostic on purpose. `platform_id` is FK to Platform registry key
    ("facebook", "linkedin"...). `external_id` is what the platform uses (group URL,
    page ID, subreddit name, Telegram chat ID, ...).
    """
    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform_id: Mapped[str] = mapped_column(String(50))  # "facebook", "linkedin"...
    external_id: Mapped[str] = mapped_column(String(500))  # group URL, page id, ...
    name: Mapped[str] = mapped_column(String(255))
    # Categorization for targeting
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    list_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    member_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Post(Base):
    """A single logical post. May have many PostVariants (spintax per target)."""
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_type: Mapped[PostType] = mapped_column(Enum(PostType))
    status: Mapped[PostStatus] = mapped_column(Enum(PostStatus), default=PostStatus.DRAFT)

    # Generated content (main version — targets may have spintaxed variants)
    text: Mapped[str] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    image_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    cta_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Scheduling
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Generation metadata
    generation_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    generation_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    variants: Mapped[list[PostVariant]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )
    feedback: Mapped[list[Feedback]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )


class PostVariant(Base):
    """Smart spintax variant of a post for a specific target.

    One per (post_id, target_id) pair. Text is a reformulation of the main Post.text
    so no two groups get the same wording.
    """
    __tablename__ = "post_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"))
    target_id: Mapped[int] = mapped_column(ForeignKey("targets.id"))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[PostStatus] = mapped_column(Enum(PostStatus), default=PostStatus.SCHEDULED)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    external_post_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    post: Mapped[Post] = relationship(back_populates="variants")


class Feedback(Base):
    """Thumbs up/down on a post. Used as few-shot examples for future generations."""
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"))
    rating: Mapped[FeedbackRating] = mapped_column(Enum(FeedbackRating))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    post: Mapped[Post] = relationship(back_populates="feedback")


class BlackoutDate(Base):
    """Days where no posting happens. Vacations, holidays, etc."""
    __tablename__ = "blackout_dates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(DateTime)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)


class LogEntry(Base):
    """Activity log for observability."""
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(20))  # info, warn, error
    category: Mapped[str] = mapped_column(String(50))  # scheduler, ai, posting, ws
    message: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
