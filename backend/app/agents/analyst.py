"""SMM Analyst agent (M6).

Given the last N days of posts + their collected metrics, ask Claude for a
structured analysis:

- `summary` — one paragraph the user reads on the dashboard
- `top_performers` / `bottom_performers` — post_ids + why
- `patterns` — observations about post_type / time_of_day / length / tone
- `proposals` — concrete mutations for BusinessProfile / posting strategy

We store the full JSON body and emit OptimizerProposal rows so the user can
review them one-by-one.

Proposal confidence thresholds (tunable in one place):
- auto-apply ONLY for `posting_window_*`, `post_type_ratios`, `emoji_density`
  when `confidence >= 0.75` — safe, revertable, small-blast-radius.
- everything else stays PENDING until a human clicks Apply.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from anthropic import Anthropic
from sqlalchemy.orm import Session

from app.agents import MalformedLLMResponse
from app.config import settings
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

log = logging.getLogger("agents.analyst")

_COST_IN = 3.0 / 1_000_000
_COST_OUT = 15.0 / 1_000_000


# Fields that can be auto-applied safely when the agent is confident enough.
AUTO_APPLIABLE_FIELDS = {
    "posting_window_start_hour",
    "posting_window_end_hour",
    "post_type_ratios",
    "emoji_density",
    "posts_per_day",
}

AUTO_APPLY_CONFIDENCE = 0.75


ANALYST_SYSTEM = """You are an expert SMM analyst reviewing a solo business \
owner's recent social-media performance.

The user provides:
- BusinessProfile (current tone, length, emoji density, posting windows, \
  post_type_ratios, etc.)
- A list of recent posts with their engagement metrics (likes, comments, \
  shares, engagement_score across windows 1h / 24h / 7d).

Produce a STRUCTURED JSON report. Your job:
1. Spot honest patterns (what drives engagement? what doesn't?).
2. Propose concrete, minimal mutations to the profile that would plausibly \
  lift numbers next period.
3. Flag which proposals are safe to auto-apply (small, revertable) and which \
  need the human to decide.

## Output — single JSON object, nothing else:
{
  "summary": "One-paragraph human-facing takeaway (2–3 sentences).",
  "top_performers": [{"post_id": 12, "why": "Short, concrete, morning slot."}],
  "bottom_performers": [{"post_id": 7, "why": "Long salesy hook; posted at \
22:00 weekday."}],
  "patterns": [
    "Informative posts at 9-11am get 2x engagement of ones posted 18-21.",
    "Posts with a concrete number in the opening hook outperform generic ones."
  ],
  "proposals": [
    {
      "field": "posting_window_start_hour",
      "current_value": 9,
      "proposed_value": 10,
      "reasoning": "3 of 4 top performers were posted after 10am; 9-10am \
underperforms by 40%.",
      "confidence": 0.8
    },
    {
      "field": "post_type_ratios",
      "current_value": {"informative": 0.5, "hard_sell": 0.2},
      "proposed_value": {"informative": 0.6, "hard_sell": 0.1},
      "reasoning": "Hard-sell variants score 3x lower than informative.",
      "confidence": 0.7
    }
  ]
}

Guidelines:
- Proposals MUST reference real fields on BusinessProfile: \
  posting_window_start_hour, posting_window_end_hour, post_type_ratios, \
  tone, length, emoji_density, posts_per_day.
- Keep confidence honest — 0.9+ only if you see a clear pattern with n>=5.
- Be concrete in reasoning; name specific posts or metrics.
- 2–5 proposals is plenty. If there's no signal yet, return an empty \
  proposals array and say so in the summary.
"""


@dataclass
class ProposalPayload:
    field: str
    current_value: object
    proposed_value: object
    reasoning: str
    confidence: float


@dataclass
class AnalystOutput:
    summary: str
    body: dict
    proposals: list[ProposalPayload] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1 or first > last:
        raise MalformedLLMResponse(f"No JSON in analyst response: {text[:300]!r}")
    snippet = text[first : last + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError as exc:
        raise MalformedLLMResponse(
            f"Analyst returned malformed JSON: {exc.msg} (snippet: {snippet[:200]!r})"
        ) from exc


def _posts_block(db: Session, period_start: datetime, period_end: datetime) -> str:
    """JSON-serialize posts posted in the window plus their metrics."""
    rows: list[dict] = []
    posts: list[Post] = (
        db.query(Post)
        .filter(Post.status == PostStatus.POSTED)
        .filter(Post.posted_at >= period_start)
        .filter(Post.posted_at <= period_end)
        .all()
    )
    for post in posts:
        metrics: list[PostMetrics] = (
            db.query(PostMetrics)
            .join(PostVariant, PostMetrics.variant_id == PostVariant.id)
            .filter(PostVariant.post_id == post.id)
            .all()
        )
        # Collapse to per-post max for each window (in case multi-variant).
        by_window: dict[str, dict] = {}
        for m in metrics:
            key = m.window.value
            cur = by_window.get(key)
            if cur is None or m.engagement_score > cur["engagement_score"]:
                by_window[key] = {
                    "likes": m.likes,
                    "comments": m.comments,
                    "shares": m.shares,
                    "reach": m.reach,
                    "engagement_score": m.engagement_score,
                }
        rows.append(
            {
                "post_id": post.id,
                "post_type": post.post_type.value,
                "posted_at": post.posted_at.isoformat() if post.posted_at else None,
                "length_chars": len(post.text),
                "text_preview": post.text[:200],
                "metrics": by_window,
            }
        )
    return json.dumps(rows, ensure_ascii=False, indent=2)


def _profile_block(profile: BusinessProfile) -> str:
    return json.dumps(
        {
            "tone": profile.tone.value,
            "length": profile.length.value,
            "emoji_density": profile.emoji_density.value,
            "posting_window_start_hour": profile.posting_window_start_hour,
            "posting_window_end_hour": profile.posting_window_end_hour,
            "posts_per_day": profile.posts_per_day,
            "post_type_ratios": profile.post_type_ratios or {},
            "language": profile.language,
        },
        ensure_ascii=False,
        indent=2,
    )


def run_analysis(
    db: Session,
    profile: BusinessProfile,
    period_start: datetime,
    period_end: datetime,
) -> AnalystOutput:
    """Invoke Claude and parse the structured report."""
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    posts_json = _posts_block(db, period_start, period_end)
    profile_json = _profile_block(profile)
    user = (
        "## BusinessProfile\n"
        f"{profile_json}\n\n"
        f"## Posts in window {period_start.date()} → {period_end.date()}\n"
        f"{posts_json}\n"
    )

    client = Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=settings.text_model,
        max_tokens=3000,
        system=ANALYST_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    raw = resp.content[0].text
    data = _extract_json(raw)
    proposals = [
        ProposalPayload(
            field=p.get("field", ""),
            current_value=p.get("current_value"),
            proposed_value=p.get("proposed_value"),
            reasoning=p.get("reasoning", ""),
            confidence=float(p.get("confidence", 0.5)),
        )
        for p in (data.get("proposals") or [])
        if p.get("field")
    ]
    in_tokens = resp.usage.input_tokens
    out_tokens = resp.usage.output_tokens
    cost = in_tokens * _COST_IN + out_tokens * _COST_OUT
    return AnalystOutput(
        summary=data.get("summary", ""),
        body=data,
        proposals=proposals,
        input_tokens=in_tokens,
        output_tokens=out_tokens,
        cost_usd=cost,
        model=settings.text_model,
    )


def apply_proposal(db: Session, profile: BusinessProfile, proposal: OptimizerProposal) -> None:
    """Mutate BusinessProfile in-place with `proposal.proposed_value`. Commits."""
    field_name = proposal.field
    if not hasattr(profile, field_name):
        raise ValueError(f"Unknown BusinessProfile field: {field_name}")
    setattr(profile, field_name, proposal.proposed_value)
    proposal.status = ProposalStatus.APPLIED
    proposal.applied_at = datetime.now(UTC)
    db.commit()


def persist_report_and_proposals(
    db: Session,
    profile: BusinessProfile,
    output: AnalystOutput,
    period_start: datetime,
    period_end: datetime,
) -> AnalystReport:
    """Write the report + N proposal rows. Auto-applies small safe ones."""
    report = AnalystReport(
        period_start=period_start,
        period_end=period_end,
        summary=output.summary,
        body=output.body,
        cost_usd=output.cost_usd,
        model=output.model,
    )
    db.add(report)
    db.flush()  # get id

    for p in output.proposals:
        eligible = (
            p.field in AUTO_APPLIABLE_FIELDS
            and p.confidence >= AUTO_APPLY_CONFIDENCE
        )
        proposal = OptimizerProposal(
            report_id=report.id,
            field=p.field,
            # JSON columns want dict/list — wrap scalars consistently so UI can
            # introspect.
            current_value={"value": p.current_value} if not isinstance(p.current_value, dict) else p.current_value,
            proposed_value={"value": p.proposed_value} if not isinstance(p.proposed_value, dict) else p.proposed_value,
            reasoning=p.reasoning,
            confidence=p.confidence,
            status=ProposalStatus.PENDING,
            auto_applied=False,
        )
        db.add(proposal)
        db.flush()
        if eligible and hasattr(profile, p.field):
            # Unwrap scalar for assignment.
            value = p.proposed_value
            try:
                setattr(profile, p.field, value)
                proposal.status = ProposalStatus.APPLIED
                proposal.auto_applied = True
                proposal.applied_at = datetime.now(UTC)
            except Exception as exc:
                log.warning("Auto-apply failed for %s: %s", p.field, exc)
    db.commit()
    return report


def default_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Last 7 days, inclusive."""
    now = now or datetime.now(UTC)
    return (now - timedelta(days=7), now)
