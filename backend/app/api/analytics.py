"""Analytics / Analyst / Optimizer routes (M6).

Surfaces:
- Raw metrics for a post / the whole queue.
- Weekly Analyst reports (list + detail, plus a manual generate trigger).
- Optimizer proposals (list + apply + reject).
- Manual `/metrics/collect` trigger so you can refresh without waiting for the
  hourly cron during development.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.agents import analyst as analyst_agent
from app.db import get_session
from app.db.models import (
    AnalystReport,
    BusinessProfile,
    OptimizerProposal,
    Post,
    PostMetrics,
    PostStatus,
    PostVariant,
    ProposalStatus,
)
from app.schemas import (
    AnalystGenerateRequest,
    AnalystReportOut,
    AnalyticsSummaryOut,
    MetricsCollectResult,
    OptimizerProposalOut,
    PostMetricsOut,
    TopPerformerOut,
)
from app.services import few_shot, metrics as metrics_service

log = logging.getLogger("api.analytics")

router = APIRouter(prefix="/api", tags=["analytics"])


# ---------- Metrics ----------


@router.get("/metrics/post/{post_id}", response_model=list[PostMetricsOut])
def post_metrics(post_id: int, db: Session = Depends(get_session)) -> list[PostMetrics]:
    return (
        db.query(PostMetrics)
        .join(PostVariant, PostMetrics.variant_id == PostVariant.id)
        .filter(PostVariant.post_id == post_id)
        .order_by(PostMetrics.collected_at.desc())
        .all()
    )


@router.post("/metrics/collect", response_model=MetricsCollectResult)
async def collect_metrics_now(db: Session = Depends(get_session)) -> MetricsCollectResult:
    """Manual trigger — runs a full collection pass synchronously."""
    try:
        result = await metrics_service.collect_metrics(db)
    except Exception as exc:
        log.exception("Metrics collection failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return MetricsCollectResult(**result)


@router.get("/analytics/summary", response_model=AnalyticsSummaryOut)
def analytics_summary(
    days: int = 7,
    db: Session = Depends(get_session),
) -> AnalyticsSummaryOut:
    """Quick KPI block for the dashboard home."""
    period_start = datetime.now(UTC) - timedelta(days=days)
    total_posts = (
        db.query(func.count(Post.id))
        .filter(Post.status == PostStatus.POSTED)
        .filter(Post.posted_at >= period_start)
        .scalar()
        or 0
    )
    totals = (
        db.query(
            func.coalesce(func.sum(PostMetrics.likes), 0),
            func.coalesce(func.sum(PostMetrics.comments), 0),
            func.coalesce(func.sum(PostMetrics.shares), 0),
            func.coalesce(func.avg(PostMetrics.engagement_score), 0.0),
        )
        .join(PostVariant, PostMetrics.variant_id == PostVariant.id)
        .join(Post, Post.id == PostVariant.post_id)
        .filter(Post.posted_at >= period_start)
        .first()
        or (0, 0, 0, 0.0)
    )
    return AnalyticsSummaryOut(
        period_days=days,
        posts=int(total_posts),
        likes=int(totals[0]),
        comments=int(totals[1]),
        shares=int(totals[2]),
        avg_engagement_score=float(totals[3] or 0.0),
    )


@router.get("/analytics/top-performers", response_model=list[TopPerformerOut])
def top_performers(
    days: int = 7,
    limit: int = 5,
    reverse: bool = False,
    db: Session = Depends(get_session),
) -> list[TopPerformerOut]:
    """Best (or worst, if reverse=true) posts in the window by engagement_score."""
    period_start = datetime.now(UTC) - timedelta(days=days)
    best_score = func.max(PostMetrics.engagement_score).label("best")
    rows = (
        db.query(Post, best_score)
        .join(PostVariant, PostVariant.post_id == Post.id)
        .join(PostMetrics, PostMetrics.variant_id == PostVariant.id)
        .filter(Post.posted_at >= period_start)
        .group_by(Post.id)
        .order_by(best_score.asc() if reverse else best_score.desc())
        .limit(limit)
        .all()
    )
    return [
        TopPerformerOut(
            post_id=p.id,
            post_type=p.post_type,
            posted_at=p.posted_at,
            text_preview=p.text[:200],
            engagement_score=float(score or 0.0),
        )
        for p, score in rows
    ]


# ---------- Analyst reports ----------


@router.get("/analyst/reports", response_model=list[AnalystReportOut])
def list_reports(
    limit: int = 20,
    db: Session = Depends(get_session),
) -> list[AnalystReport]:
    return (
        db.query(AnalystReport)
        .order_by(AnalystReport.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/analyst/reports/{report_id}", response_model=AnalystReportOut)
def get_report(report_id: int, db: Session = Depends(get_session)) -> AnalystReport:
    r = db.get(AnalystReport, report_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return r


@router.post("/analyst/generate", response_model=AnalystReportOut)
async def generate_report(
    payload: AnalystGenerateRequest,
    db: Session = Depends(get_session),
) -> AnalystReport:
    """Kick off a fresh analyst run. Blocks until Claude responds."""
    profile = db.query(BusinessProfile).order_by(BusinessProfile.id.asc()).first()
    if profile is None:
        raise HTTPException(status_code=400, detail="Business profile required.")

    end = payload.period_end or datetime.now(UTC)
    start = payload.period_start or (end - timedelta(days=payload.days or 7))

    # The Claude call can be slow; run it in a thread so we don't hog the loop.
    output = await asyncio.to_thread(analyst_agent.run_analysis, db, profile, start, end)
    report = analyst_agent.persist_report_and_proposals(db, profile, output, start, end)

    # Side-effect: refresh few-shot store now that we have fresh metrics.
    try:
        few_shot.refresh_few_shot_store(db)
    except Exception:
        log.exception("Few-shot refresh failed (non-fatal)")

    return report


# ---------- Proposals ----------


@router.get("/optimizer/proposals", response_model=list[OptimizerProposalOut])
def list_proposals(
    status: ProposalStatus | None = None,
    limit: int = 100,
    db: Session = Depends(get_session),
) -> list[OptimizerProposal]:
    q = db.query(OptimizerProposal)
    if status is not None:
        q = q.filter(OptimizerProposal.status == status)
    return q.order_by(OptimizerProposal.created_at.desc()).limit(limit).all()


@router.post("/optimizer/proposals/{proposal_id}/apply", response_model=OptimizerProposalOut)
def apply_proposal(proposal_id: int, db: Session = Depends(get_session)) -> OptimizerProposal:
    proposal = db.get(OptimizerProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status != ProposalStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Proposal is already {proposal.status.value}.",
        )
    profile = db.query(BusinessProfile).order_by(BusinessProfile.id.asc()).first()
    if profile is None:
        raise HTTPException(status_code=400, detail="Business profile required.")
    # Unwrap scalar container if that's how the agent stored it.
    value = proposal.proposed_value
    if isinstance(value, dict) and "value" in value and len(value) == 1:
        value = value["value"]
    if not hasattr(profile, proposal.field):
        raise HTTPException(status_code=400, detail=f"Unknown field {proposal.field}")
    setattr(profile, proposal.field, value)
    proposal.status = ProposalStatus.APPLIED
    proposal.applied_at = datetime.now(UTC)
    db.commit()
    db.refresh(proposal)
    return proposal


@router.post("/optimizer/proposals/{proposal_id}/reject", response_model=OptimizerProposalOut)
def reject_proposal(proposal_id: int, db: Session = Depends(get_session)) -> OptimizerProposal:
    proposal = db.get(OptimizerProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status != ProposalStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Proposal is already {proposal.status.value}.",
        )
    proposal.status = ProposalStatus.REJECTED
    db.commit()
    db.refresh(proposal)
    return proposal


# ---------- Few-shot store ----------


@router.post("/few-shot/refresh")
def refresh_few_shot(db: Session = Depends(get_session)) -> dict:
    count = few_shot.refresh_few_shot_store(db)
    return {"inserted": count}
