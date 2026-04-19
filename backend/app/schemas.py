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
    MediaKind,
    MetricsWindow,
    PlanStatus,
    PostStatus,
    PostType,
    ProposalStatus,
    SessionHealthStatus,
    SlotStatus,
    TargetReviewStatus,
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
    auto_approve_types: list[str] = Field(default_factory=list)


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
    description_snippet: str | None = None
    category: str | None = None
    source: str = "manual"


class TargetPatch(BaseModel):
    name: str | None = None
    tags: list[str] | None = None
    list_name: str | None = None
    member_count: int | None = None
    active: bool | None = None
    description_snippet: str | None = None
    category: str | None = None
    review_status: TargetReviewStatus | None = None


class TargetOut(TargetIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    relevance_score: int | None = None
    ai_reasoning: str | None = None
    review_status: TargetReviewStatus = TargetReviewStatus.PENDING


# ---------- M3: Target Agent ----------


class TargetDiscoverResult(BaseModel):
    created: int
    updated: int
    targets: list[TargetOut]


class TargetScoreRequest(BaseModel):
    """Score a specific subset. Empty = score all unscored pending targets."""

    target_ids: list[int] = Field(default_factory=list)


class TargetScoreItem(BaseModel):
    target_id: int
    score: int
    reasoning: str


class TargetScoreResponse(BaseModel):
    scored: list[TargetScoreItem]
    cost_usd: float


class TargetClusterRequest(BaseModel):
    """Cluster approved targets. Empty `target_ids` = all approved."""

    target_ids: list[int] = Field(default_factory=list)


class TargetClusterGroup(BaseModel):
    list_name: str
    target_ids: list[int]


class TargetClusterResponse(BaseModel):
    lists: list[TargetClusterGroup]
    cost_usd: float


class TargetBulkReviewRequest(BaseModel):
    target_ids: list[int]
    review_status: TargetReviewStatus


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
    ab_arm: str | None = None


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    post_type: PostType
    status: PostStatus
    text: str
    image_url: str | None
    image_prompt: str | None
    media_asset_id: int | None = None
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

    id: int
    url: str  # relative to backend root, e.g. "/static/images/uploads/abc.png"
    filename: str
    mime: str
    size_bytes: int
    width: int | None = None
    height: int | None = None


class MediaAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: MediaKind
    mime: str
    local_path: str
    filename: str
    size_bytes: int
    width: int | None
    height: int | None
    duration_sec: float | None
    ai_caption: str | None
    ai_tags: list[str]
    tags_user: list[str]
    tagged_at: datetime | None
    created_at: datetime

    @property
    def url(self) -> str:
        return f"/static/{self.local_path}"


class MediaAssetPatch(BaseModel):
    tags_user: list[str] | None = None
    ai_caption: str | None = None


class MediaTagResult(BaseModel):
    caption: str
    tags: list[str]
    cost_usd: float


class MediaSuggestion(BaseModel):
    asset: MediaAssetOut
    score: float


# ---------- Status ----------


class StatusOut(BaseModel):
    ok: bool
    version: str
    extension_connected: bool
    scheduler_running: bool
    next_scheduled_post_at: datetime | None
    pending_posts: int


# ---------- Content Plan (M1) ----------


class PlanSlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int
    scheduled_for: datetime
    post_type: PostType
    topic_hint: str | None
    rationale: str | None
    status: SlotStatus
    post_id: int | None
    media_asset_id: int | None = None
    notes: str | None
    created_at: datetime


class PlanSlotIn(BaseModel):
    scheduled_for: datetime
    post_type: PostType
    topic_hint: str | None = None
    rationale: str | None = None
    notes: str | None = None


class PlanSlotPatch(BaseModel):
    scheduled_for: datetime | None = None
    post_type: PostType | None = None
    topic_hint: str | None = None
    rationale: str | None = None
    notes: str | None = None
    status: SlotStatus | None = None


class ContentPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    goal: str | None
    start_date: datetime
    end_date: datetime
    status: PlanStatus
    generation_params: dict
    chat_history: list
    generation_cost_usd: float
    created_at: datetime
    updated_at: datetime
    slots: list[PlanSlotOut] = Field(default_factory=list)


class ContentPlanPatch(BaseModel):
    name: str | None = None
    goal: str | None = None
    status: PlanStatus | None = None


class PlanGenerateRequest(BaseModel):
    """Ask the PlannerAgent to generate a new plan.

    `replace_existing_slots` — if true and the plan already has slots, delete them
    before inserting new ones.
    """

    name: str
    goal: str | None = None
    start_date: datetime
    end_date: datetime
    replace_existing_slots: bool = True


class PlanChatRequest(BaseModel):
    message: str


class PlanChatResponse(BaseModel):
    reply: str
    updated: bool
    plan: ContentPlanOut


class SlotGeneratePostResponse(BaseModel):
    """Returned after generating a Post from a slot."""

    slot: PlanSlotOut
    post: PostOut


# ---------- Humanizer (M4) ----------


class HumanizerProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    typing_wpm_min: int
    typing_wpm_max: int
    mistake_rate: float
    pause_between_sentences_ms_min: int
    pause_between_sentences_ms_max: int
    mouse_path_curvature: float
    idle_scroll_before_post_sec_min: int
    idle_scroll_before_post_sec_max: int
    schedule_jitter_minutes: int
    consecutive_failures_threshold: int
    smart_pause_minutes: int
    smart_pause_until: datetime | None
    smart_pause_reason: str | None


class HumanizerProfileIn(BaseModel):
    typing_wpm_min: int | None = None
    typing_wpm_max: int | None = None
    mistake_rate: float | None = None
    pause_between_sentences_ms_min: int | None = None
    pause_between_sentences_ms_max: int | None = None
    mouse_path_curvature: float | None = None
    idle_scroll_before_post_sec_min: int | None = None
    idle_scroll_before_post_sec_max: int | None = None
    schedule_jitter_minutes: int | None = None
    consecutive_failures_threshold: int | None = None
    smart_pause_minutes: int | None = None


class SessionHealthOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    platform_id: str
    status: SessionHealthStatus
    consecutive_failures: int
    last_failure_at: datetime | None
    last_failure_reason: str | None
    last_success_at: datetime | None


class SmartPauseInfo(BaseModel):
    paused: bool
    until: datetime | None
    reason: str | None


class BlackoutDateIn(BaseModel):
    date: datetime
    reason: str | None = None


class BlackoutDateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: datetime
    reason: str | None


# ---------- Review & Approval (M5) ----------


class PostApproveRequest(BaseModel):
    """Approve a PENDING_REVIEW post. If `scheduled_for` is set, the post is
    scheduled with variants; otherwise it transitions to DRAFT for later action.
    """

    target_ids: list[int] = Field(default_factory=list)
    scheduled_for: datetime | None = None


class PostRejectRequest(BaseModel):
    reason: str | None = None


class PostRegenerateRequest(BaseModel):
    topic_hint: str | None = None
    generate_image: bool = False


class PostApproveAllRequest(BaseModel):
    post_type: PostType | None = None
    scheduled_for: datetime | None = None


# ---------- Analytics & Analyst (M6) ----------


class PostMetricsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    variant_id: int
    window: MetricsWindow
    likes: int
    comments: int
    shares: int
    reach: int | None
    engagement_score: float
    collected_at: datetime


class MetricsCollectResult(BaseModel):
    variants_touched: int
    rows_created: int


class AnalyticsSummaryOut(BaseModel):
    period_days: int
    posts: int
    likes: int
    comments: int
    shares: int
    avg_engagement_score: float


class TopPerformerOut(BaseModel):
    post_id: int
    post_type: PostType
    posted_at: datetime | None
    text_preview: str
    engagement_score: float


class AnalystReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    period_start: datetime
    period_end: datetime
    summary: str
    body: dict
    cost_usd: float
    model: str
    created_at: datetime


class AnalystGenerateRequest(BaseModel):
    days: int | None = 7
    period_start: datetime | None = None
    period_end: datetime | None = None


class OptimizerProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_id: int | None
    field: str
    current_value: dict
    proposed_value: dict
    reasoning: str
    confidence: float
    status: ProposalStatus
    auto_applied: bool
    applied_at: datetime | None
    created_at: datetime


# ---------- Platform credentials + OAuth (M7) ----------


class PlatformCredentialOut(BaseModel):
    """Safe view of a PlatformCredential — never returns the access_token."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: str
    account_id: str
    username: str | None
    token_expires_at: datetime | None
    extra: dict
    created_at: datetime
    updated_at: datetime


class MetaOAuthUrlOut(BaseModel):
    """The login URL we redirect the user to. `state` is random per request."""

    url: str
    state: str


class MetaOAuthCompleteOut(BaseModel):
    """Summary of what the callback stored."""

    instagram: PlatformCredentialOut | None = None
    threads: PlatformCredentialOut | None = None
    message: str


class MetaManualCredentialIn(BaseModel):
    """Escape hatch for CLI users — paste a long-lived token + account id(s)
    directly without running through the OAuth redirect.
    """

    platform_id: str  # "instagram" or "threads"
    account_id: str
    username: str | None = None
    access_token: str
