"""Dashboard overview — one aggregator endpoint so the guided home page
doesn't need to fan out into 6 separate requests.

The shape is deliberately flat and UI-oriented: we compute *next_step* on
the backend where all state lives, and the frontend just renders it. This
keeps the home page "what do I do next?" logic testable in one place.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_session
from app.db.models import (
    BusinessProfile,
    ContentPlan,
    PlanStatus,
    PlatformCredential,
    Post,
    PostStatus,
    PostVariant,
    Target,
)
from app.ws.extension_bridge import bridge

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


NextStepId = Literal[
    "connect_extension",
    "create_profile",
    "connect_platform",
    "add_targets",
    "generate_plan",
    "review_drafts",
    "resolve_failures",
    "refresh_tokens",
    "all_set",
]


class NextStep(BaseModel):
    id: NextStepId
    title: str
    description: str
    cta_label: str
    cta_href: str


class SetupBlock(BaseModel):
    backend_ok: bool
    extension_connected: bool
    scheduler_running: bool
    has_business_profile: bool
    platforms_connected: int
    # Subset of platforms_connected: Meta-backed creds whose token expires
    # within the next 7 days.
    platforms_expiring_soon: int
    targets_active: int
    plans_active: int


class PublishingNow(BaseModel):
    variant_id: int
    post_id: int
    target_name: str
    platform_id: str
    started_at: datetime | None


class NextScheduled(BaseModel):
    variant_id: int
    post_id: int
    target_name: str
    platform_id: str
    scheduled_for: datetime


class RecentFailure(BaseModel):
    variant_id: int
    post_id: int
    target_name: str
    platform_id: str
    error: str
    updated_at: datetime
    # User-actionable problems (not-a-group-member, checkpoint) surface
    # differently in the UI so transient / permanent classifications don't
    # get blurred together.
    kind: Literal["permanent", "transient"]


class ActivityBlock(BaseModel):
    publishing_now: PublishingNow | None
    next_scheduled: NextScheduled | None
    pending_review: int
    failed_last_24h: int
    scheduled_total: int
    posted_today: int
    drafts: int
    recent_failures: list[RecentFailure]


class DashboardOverview(BaseModel):
    next_step: NextStep
    setup: SetupBlock
    activity: ActivityBlock


_PERMANENT_MARKERS = ("not_a_group_member", "checkpoint_detected")


def _classify_error(err: str | None) -> Literal["permanent", "transient"]:
    if not err:
        return "transient"
    return "permanent" if any(m in err for m in _PERMANENT_MARKERS) else "transient"


def _compute_next_step(
    *,
    extension_connected: bool,
    has_profile: bool,
    platforms_connected: int,
    targets_active: int,
    expiring_soon: int,
    pending_review: int,
    plans_active: int,
    scheduled_total: int,
    permanent_failures: int,
) -> NextStep:
    """Decide the one thing the user should do now.

    Priority order: blockers that stop anything from working (extension,
    profile, platform, target) → user-actionable failures → routine work
    (review drafts, generate plan) → housekeeping (refresh tokens) → idle.
    """
    if permanent_failures > 0:
        return NextStep(
            id="resolve_failures",
            title=f"{permanent_failures} post{'s' if permanent_failures != 1 else ''} need your attention",
            description="Some posts failed with user-actionable errors (not a member of a group, FB checkpoint, etc). Fix them, then re-queue.",
            cta_label="Open queue",
            cta_href="/queue",
        )
    if not extension_connected and platforms_connected == 0:
        # Only push the extension when we clearly need it (no Meta creds yet
        # — the extension is the FB path). IG/Threads users without FB can
        # live without it.
        return NextStep(
            id="connect_extension",
            title="Install the Chrome extension",
            description="Facebook publishing routes through the extension. Load extension/dist as an unpacked extension in chrome://extensions.",
            cta_label="Open Platforms",
            cta_href="/platforms",
        )
    if not has_profile:
        return NextStep(
            id="create_profile",
            title="Describe your business",
            description="The generator uses your business profile as context. It takes about a minute.",
            cta_label="Fill in profile",
            cta_href="/profile",
        )
    if platforms_connected == 0:
        return NextStep(
            id="connect_platform",
            title="Connect a platform",
            description="Connect Instagram / Threads via Meta OAuth, or install the extension for Facebook Groups.",
            cta_label="Connect now",
            cta_href="/platforms",
        )
    if targets_active == 0:
        return NextStep(
            id="add_targets",
            title="Add targets to post to",
            description="Pick FB groups, IG accounts, or threads to publish to. The scheduler won't do anything without at least one active target.",
            cta_label="Manage targets",
            cta_href="/targets",
        )
    if pending_review > 0:
        return NextStep(
            id="review_drafts",
            title=f"Review {pending_review} draft{'s' if pending_review != 1 else ''}",
            description="Drafts you approve go to the queue; the rest stay here.",
            cta_label="Open review",
            cta_href="/review",
        )
    if plans_active == 0 and scheduled_total == 0:
        return NextStep(
            id="generate_plan",
            title="Generate a content plan",
            description="Generate a week of posts from your profile + targets, then review and approve.",
            cta_label="Plan content",
            cta_href="/plans",
        )
    if expiring_soon > 0:
        return NextStep(
            id="refresh_tokens",
            title=f"{expiring_soon} Meta token{'s' if expiring_soon != 1 else ''} expiring soon",
            description="The scheduler auto-refreshes nightly, but you can refresh now if you want to be safe.",
            cta_label="Open Platforms",
            cta_href="/platforms",
        )
    return NextStep(
        id="all_set",
        title="All set",
        description="Posting is scheduled and on track. You don't need to do anything right now.",
        cta_label="Open queue",
        cta_href="/queue",
    )


@router.get("/overview", response_model=DashboardOverview)
def overview(db: Session = Depends(get_session)) -> DashboardOverview:
    from app.scheduler import scheduler as app_scheduler

    now = datetime.now(UTC)
    # SQLite stores naive UTC — normalise the comparison baseline.
    now_naive = now.replace(tzinfo=None)
    day_ago = now_naive - timedelta(days=1)
    start_of_day = now_naive.replace(hour=0, minute=0, second=0, microsecond=0)

    # --- Setup block ---
    has_profile = db.query(BusinessProfile).first() is not None
    platforms_connected = db.query(PlatformCredential).count()
    targets_active = (
        db.query(Target)
        .filter(Target.active.is_(True))
        .filter(Target.review_status != "rejected")
        .count()
    )
    plans_active = (
        db.query(ContentPlan)
        .filter(ContentPlan.status == PlanStatus.ACTIVE)
        .count()
    )
    expiring_soon = (
        db.query(PlatformCredential)
        .filter(PlatformCredential.token_expires_at.isnot(None))
        .filter(
            PlatformCredential.token_expires_at <= now_naive + timedelta(days=7)
        )
        .count()
    )

    # --- Activity block ---
    pending_review = (
        db.query(Post).filter(Post.status == PostStatus.PENDING_REVIEW).count()
    )
    drafts = db.query(Post).filter(Post.status == PostStatus.DRAFT).count()
    scheduled_total = (
        db.query(PostVariant)
        .filter(PostVariant.status == PostStatus.SCHEDULED)
        .count()
    )
    posted_today = (
        db.query(PostVariant)
        .filter(PostVariant.status == PostStatus.POSTED)
        .filter(PostVariant.posted_at >= start_of_day)
        .count()
    )
    failed_last_24h = (
        db.query(PostVariant)
        .filter(PostVariant.status == PostStatus.FAILED)
        .count()
    )

    publishing_row = (
        db.query(PostVariant)
        .filter(PostVariant.status == PostStatus.POSTING)
        .order_by(PostVariant.id.desc())
        .first()
    )
    publishing_now: PublishingNow | None = None
    if publishing_row is not None:
        target = db.get(Target, publishing_row.target_id)
        publishing_now = PublishingNow(
            variant_id=publishing_row.id,
            post_id=publishing_row.post_id,
            target_name=target.name if target else "unknown",
            platform_id=target.platform_id if target else "unknown",
            started_at=publishing_row.scheduled_for,
        )

    next_sched_row = (
        db.query(PostVariant)
        .filter(PostVariant.status == PostStatus.SCHEDULED)
        .filter(PostVariant.scheduled_for.isnot(None))
        .order_by(PostVariant.scheduled_for.asc())
        .first()
    )
    next_scheduled: NextScheduled | None = None
    if next_sched_row is not None and next_sched_row.scheduled_for is not None:
        target = db.get(Target, next_sched_row.target_id)
        next_scheduled = NextScheduled(
            variant_id=next_sched_row.id,
            post_id=next_sched_row.post_id,
            target_name=target.name if target else "unknown",
            platform_id=target.platform_id if target else "unknown",
            scheduled_for=next_sched_row.scheduled_for,
        )

    # Recent failures — last 5, any time. These fuel both the "resolve
    # failures" next-step decision and the activity panel.
    recent_rows = (
        db.query(PostVariant)
        .filter(PostVariant.status == PostStatus.FAILED)
        .order_by(PostVariant.id.desc())
        .limit(5)
        .all()
    )
    recent_failures: list[RecentFailure] = []
    for r in recent_rows:
        target = db.get(Target, r.target_id)
        recent_failures.append(
            RecentFailure(
                variant_id=r.id,
                post_id=r.post_id,
                target_name=target.name if target else "unknown",
                platform_id=target.platform_id if target else "unknown",
                error=r.error or "unknown",
                updated_at=r.posted_at or r.scheduled_for or now_naive,
                kind=_classify_error(r.error),
            )
        )
    permanent_failures = sum(1 for f in recent_failures if f.kind == "permanent")

    next_step = _compute_next_step(
        extension_connected=bridge.connected,
        has_profile=has_profile,
        platforms_connected=platforms_connected,
        targets_active=targets_active,
        expiring_soon=expiring_soon,
        pending_review=pending_review,
        plans_active=plans_active,
        scheduled_total=scheduled_total,
        permanent_failures=permanent_failures,
    )

    return DashboardOverview(
        next_step=next_step,
        setup=SetupBlock(
            backend_ok=True,
            extension_connected=bridge.connected,
            scheduler_running=app_scheduler.is_running(),
            has_business_profile=has_profile,
            platforms_connected=platforms_connected,
            platforms_expiring_soon=expiring_soon,
            targets_active=targets_active,
            plans_active=plans_active,
        ),
        activity=ActivityBlock(
            publishing_now=publishing_now,
            next_scheduled=next_scheduled,
            pending_review=pending_review,
            failed_last_24h=failed_last_24h,
            scheduled_total=scheduled_total,
            posted_today=posted_today,
            drafts=drafts,
            recent_failures=recent_failures,
        ),
    )
