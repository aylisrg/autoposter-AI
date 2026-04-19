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
    # M5 — auto-approve list: post_type values that skip the review queue
    # entirely (e.g. ["informative", "motivational"] after you trust the agent).
    auto_approve_types: Mapped[list[str]] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class TargetReviewStatus(str, enum.Enum):
    """M3: user decision on a scraped target."""
    PENDING = "pending"      # Scraped but user hasn't seen it yet
    APPROVED = "approved"    # User wants to post here
    REJECTED = "rejected"    # User does NOT want to post here


class Target(Base):
    """A place to post to: FB group, FB page, LinkedIn profile, X account, subreddit, etc.

    Platform-agnostic on purpose. `platform_id` is FK to Platform registry key
    ("facebook", "linkedin"...). `external_id` is what the platform uses (group URL,
    page ID, subreddit name, Telegram chat ID, ...).

    M3 fields: `description_snippet` / `category` are scraped from FB; `relevance_score`
    and `ai_reasoning` are the TargetAgent's judgement; `review_status` tracks whether
    the user has approved this target. `source` = "manual" | "scraped_joined" |
    "scraped_suggested".
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

    # M3 — discovery + AI scoring
    description_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    relevance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100
    ai_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[TargetReviewStatus] = mapped_column(
        Enum(TargetReviewStatus), default=TargetReviewStatus.PENDING
    )
    source: Mapped[str] = mapped_column(String(30), default="manual")

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
    media_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_assets.id"), nullable=True
    )
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


# ---------- Content Planner (M1) ----------


class PlanStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class SlotStatus(str, enum.Enum):
    PLANNED = "planned"       # Slot exists, no Post yet
    GENERATED = "generated"   # Post drafted from slot
    SCHEDULED = "scheduled"   # Post scheduled for publishing
    POSTED = "posted"         # Published
    SKIPPED = "skipped"       # User chose to skip


class ContentPlan(Base):
    """A content plan covers a date range and groups many PlanSlots.

    One business profile can have many plans (e.g. "Q2 launch", "July specials").
    Only one is usually `active` at a time, but that's not enforced — the user is free.
    """
    __tablename__ = "content_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[datetime] = mapped_column(DateTime)
    end_date: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[PlanStatus] = mapped_column(Enum(PlanStatus), default=PlanStatus.DRAFT)
    # Snapshot of knobs at generation time (tone, posts_per_day, ratios, ...)
    generation_params: Mapped[dict] = mapped_column(JSON, default=dict)
    # Transcript of planner chat turns: [{"role": "user"|"assistant", "content": "..."}]
    chat_history: Mapped[list] = mapped_column(JSON, default=list)
    generation_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    slots: Mapped[list[PlanSlot]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="PlanSlot.scheduled_for.asc()",
    )


class PlanSlot(Base):
    """A single slot inside a ContentPlan.

    A slot is a "plan to write a post of type X on date Y about topic Z". Once the user
    generates the actual post text for this slot, `post_id` is filled and `status`
    moves to GENERATED/SCHEDULED/POSTED.
    """
    __tablename__ = "plan_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("content_plans.id"))
    scheduled_for: Mapped[datetime] = mapped_column(DateTime)
    post_type: Mapped[PostType] = mapped_column(Enum(PostType))
    topic_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Planner's rationale for picking this slot — why this type, why this time
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[SlotStatus] = mapped_column(Enum(SlotStatus), default=SlotStatus.PLANNED)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"), nullable=True)
    media_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_assets.id"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    plan: Mapped[ContentPlan] = relationship(back_populates="slots")
    post: Mapped[Post | None] = relationship()
    media_asset: Mapped[MediaAsset | None] = relationship(foreign_keys=[media_asset_id])


# ---------- Media Library (M2) ----------


class MediaKind(str, enum.Enum):
    IMAGE = "image"
    VIDEO = "video"


class MediaAsset(Base):
    """Uploaded image/video with AI-derived metadata.

    `local_path` is relative to `data/` (so we serve via the /static mount). We keep
    the raw file; derived transcodes (IG-aspect, Reels-length, etc.) land in
    `variants_json` as {"ig_square": "...", "reels_9x16": "..."}.

    `ai_tags` is a shortlist of semantic tags Claude Vision produced (e.g.
    ["basil", "windowsill", "morning-light"]). `ai_caption` is a one-sentence
    description. Together they drive the top-3 suggestion feature for PlanSlots.
    """
    __tablename__ = "media_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[MediaKind] = mapped_column(Enum(MediaKind), default=MediaKind.IMAGE)
    mime: Mapped[str] = mapped_column(String(100))
    local_path: Mapped[str] = mapped_column(String(500))
    filename: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags_user: Mapped[list[str]] = mapped_column(JSON, default=list)
    variants_json: Mapped[dict] = mapped_column(JSON, default=dict)
    tagged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ---------- Humanizer (M4) ----------


class HumanizerProfile(Base):
    """Configuration for how "human" the posting simulation should feel.

    Singleton for v1 (like BusinessProfile). Holds all tunable knobs: typing speed,
    per-char variance, mistake/correction rate, mouse-path curvature, idle scroll
    time before opening composer, and the jitter window for scheduled times.

    ## Smart pause
    `consecutive_failures_threshold` / `smart_pause_minutes` drive the
    "3 fails in a row → cool down 2h" safety. Scheduler reads `smart_pause_until`
    and skips all work while it's in the future.
    """
    __tablename__ = "humanizer_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Typing simulation (extension side)
    typing_wpm_min: Mapped[int] = mapped_column(Integer, default=35)
    typing_wpm_max: Mapped[int] = mapped_column(Integer, default=70)
    mistake_rate: Mapped[float] = mapped_column(Float, default=0.02)  # 2% chars typo'd
    pause_between_sentences_ms_min: Mapped[int] = mapped_column(Integer, default=250)
    pause_between_sentences_ms_max: Mapped[int] = mapped_column(Integer, default=900)

    # Mouse / scroll (extension side)
    mouse_path_curvature: Mapped[float] = mapped_column(Float, default=0.35)
    idle_scroll_before_post_sec_min: Mapped[int] = mapped_column(Integer, default=3)
    idle_scroll_before_post_sec_max: Mapped[int] = mapped_column(Integer, default=12)

    # Scheduling jitter (backend side)
    schedule_jitter_minutes: Mapped[int] = mapped_column(Integer, default=7)

    # Smart pause
    consecutive_failures_threshold: Mapped[int] = mapped_column(Integer, default=3)
    smart_pause_minutes: Mapped[int] = mapped_column(Integer, default=120)
    smart_pause_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    smart_pause_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class SessionHealthStatus(str, enum.Enum):
    HEALTHY = "healthy"
    WARNING = "warning"          # >=1 failure but under threshold
    CHECKPOINT = "checkpoint"    # FB asking for auth / captcha
    SHADOW_BAN_SUSPECTED = "shadow_ban_suspected"
    PAUSED = "paused"            # Smart pause is active


class SessionHealth(Base):
    """Per-platform running health counter. One row per platform_id.

    Scheduler reads/writes this every tick. If status goes non-HEALTHY we stop
    publishing for that platform and surface an alert in the dashboard status widget.
    """
    __tablename__ = "session_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform_id: Mapped[str] = mapped_column(String(50), unique=True)
    status: Mapped[SessionHealthStatus] = mapped_column(
        Enum(SessionHealthStatus), default=SessionHealthStatus.HEALTHY
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


# ---------- M6: Metrics / Analyst / Optimizer ----------


class MetricsWindow(str, enum.Enum):
    """When after posting we took the snapshot. Fixed buckets keep comparison fair."""

    ONE_HOUR = "1h"
    ONE_DAY = "24h"
    SEVEN_DAY = "7d"


class PostMetrics(Base):
    """One row per (variant, window). Scheduler fills these in over the lifespan
    of a posted variant (1h, 24h, 7d).
    """

    __tablename__ = "post_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    variant_id: Mapped[int] = mapped_column(
        ForeignKey("post_variants.id", ondelete="CASCADE"), index=True
    )
    window: Mapped[MetricsWindow] = mapped_column(Enum(MetricsWindow))
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    reach: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Computed engagement score = likes + 2*comments + 3*shares (shares weigh most)
    engagement_score: Mapped[float] = mapped_column(Float, default=0.0)
    collected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AnalystReport(Base):
    """Weekly AI-generated report. The Analyst agent writes a structured JSON
    body (top/bottom performers, patterns, hypotheses) — we store it verbatim
    plus short summary text for the dashboard overview.
    """

    __tablename__ = "analyst_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period_start: Mapped[datetime] = mapped_column(DateTime)
    period_end: Mapped[datetime] = mapped_column(DateTime)
    summary: Mapped[str] = mapped_column(Text)
    body: Mapped[dict] = mapped_column(JSON, default=dict)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    model: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ProposalStatus(str, enum.Enum):
    PENDING = "pending"
    APPLIED = "applied"
    REJECTED = "rejected"


class OptimizerProposal(Base):
    """A single mutation proposal (field = new value) emitted by the Analyst.

    Minor changes (posting window +/- 1h, small ratio shifts) can be auto-applied
    if `confidence >= 0.75`. Tone / length / big ratio shifts always wait for
    human approval.
    """

    __tablename__ = "optimizer_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int | None] = mapped_column(
        ForeignKey("analyst_reports.id", ondelete="SET NULL"), nullable=True
    )
    # Dot-path on BusinessProfile, e.g. "post_type_ratios", "posting_window_start_hour".
    field: Mapped[str] = mapped_column(String(100))
    current_value: Mapped[dict] = mapped_column(JSON, default=dict)
    proposed_value: Mapped[dict] = mapped_column(JSON, default=dict)
    reasoning: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[ProposalStatus] = mapped_column(
        Enum(ProposalStatus), default=ProposalStatus.PENDING
    )
    auto_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FewShotExample(Base):
    """Curated top-performing posts used as few-shot examples for Writer.

    Refreshed periodically from PostMetrics — the N highest-engagement posts per
    post_type stay in the store; others rotate out.
    """

    __tablename__ = "few_shot_examples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), index=True
    )
    post_type: Mapped[PostType] = mapped_column(Enum(PostType), index=True)
    text: Mapped[str] = mapped_column(Text)
    engagement_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
