"""iCalendar feed of scheduled + posted posts.

Lets the user subscribe to the posting queue from Google Calendar / Apple
Calendar / Outlook. Each Post with `scheduled_for` or `posted_at` becomes a
VEVENT; the VCALENDAR wrapper is refreshed on every request (no caching —
volume is tiny).

## Auth

The normal dashboard-PIN cookie/header doesn't reach third-party calendar
clients — they do a plain anonymous GET every ~30 min. So `.ics` uses a
token derived from the PIN via HMAC: stable across restarts, impossible to
guess without the PIN, invalidated automatically if the PIN is rotated.

- `GET /api/calendar.ics?token=<t>` — the feed itself. Public path (exempt
  from DashboardAuthMiddleware) but rejects with 401 if the token is wrong.
- `GET /api/calendar/subscribe-url` — returns the full URL with token baked
  in so the dashboard can show a "copy subscription link" button. Sits
  behind the normal PIN auth.
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
from datetime import UTC, datetime, timedelta
from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.db import get_session
from app.db.models import Post, PostStatus, Target

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


# ---------- Token ----------
#
# Context string is versioned so rotating the scheme (e.g. switching to a
# per-feed secret) later won't silently keep old tokens working.
_TOKEN_CONTEXT = b"calendar-ics-v1"


def make_calendar_token(pin: str) -> str:
    mac = _hmac.new(pin.encode("utf-8"), _TOKEN_CONTEXT, hashlib.sha256).digest()
    return mac.hex()


def _verify_token(token: str, pin: str) -> bool:
    return _hmac.compare_digest(token or "", make_calendar_token(pin))


def _check_token(token: str) -> None:
    pin = settings.dashboard_pin.strip()
    if not pin:
        return  # auth disabled entirely — dev mode
    if not _verify_token(token, pin):
        raise HTTPException(status_code=401, detail="Invalid calendar token")


# ---------- iCal serialization ----------
#
# Hand-rolled to avoid a dep for ~60 lines of code. Compliant with the subset
# of RFC 5545 that calendar clients actually care about: CRLF line endings,
# TEXT-value escaping, conservative line folding.

_CAL_STATUS = {
    PostStatus.POSTED: "CONFIRMED",
    PostStatus.FAILED: "CANCELLED",
    PostStatus.SKIPPED: "CANCELLED",
}
# DRAFT / PENDING_REVIEW / SCHEDULED / POSTING — not committed yet.
_DEFAULT_CAL_STATUS = "TENTATIVE"

# Arbitrary event length — posts are instantaneous, but calendars need a
# duration to render a visible block.
_EVENT_DURATION = timedelta(minutes=15)

# 73 chars leaves room for the leading space on folded continuation lines
# and keeps us well under the 75-octet RFC 5545 cap even for multi-byte UTF-8.
_FOLD_WIDTH = 73


def _escape(text: str) -> str:
    """RFC 5545 TEXT-value escaping. Order matters — backslash first."""
    return (
        text.replace("\\", "\\\\")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def _fold(line: str) -> str:
    if len(line) <= _FOLD_WIDTH:
        return line
    chunks = [line[i : i + _FOLD_WIDTH] for i in range(0, len(line), _FOLD_WIDTH)]
    return "\r\n ".join(chunks)


def _fmt_dt(dt: datetime) -> str:
    """iCal UTC format, e.g. 20260419T203000Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _event_lines(post: Post, target_names: list[str]) -> list[str]:
    # Prefer scheduled_for; fall back to posted_at for already-published posts
    # so the calendar shows history too.
    start = post.scheduled_for or post.posted_at
    if start is None:
        return []
    end = start + _EVENT_DURATION
    snippet = post.text.strip().splitlines()[0] if post.text else ""
    summary = f"[{post.post_type.value}] {snippet[:80]}"
    description = "\n".join(
        [
            f"Status: {post.status.value}",
            f"Targets: {', '.join(target_names) if target_names else '—'}",
            "",
            post.text,
        ]
    )
    status = _CAL_STATUS.get(post.status, _DEFAULT_CAL_STATUS)
    dtstamp = _fmt_dt(post.created_at or datetime.now(UTC))
    return [
        "BEGIN:VEVENT",
        _fold(f"UID:autoposter-post-{post.id}@autoposter"),
        _fold(f"DTSTAMP:{dtstamp}"),
        _fold(f"DTSTART:{_fmt_dt(start)}"),
        _fold(f"DTEND:{_fmt_dt(end)}"),
        _fold(f"SUMMARY:{_escape(summary)}"),
        _fold(f"DESCRIPTION:{_escape(description)}"),
        f"STATUS:{status}",
        # Show the slot as "free" on the subscriber's calendar — they're not
        # actually busy, it's just an informational entry.
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    ]


def _render_calendar(posts: Iterable[Post], target_map: dict[int, str]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//autoposter-AI//Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        _fold("X-WR-CALNAME:autoposter-AI — Scheduled Posts"),
        _fold("X-WR-CALDESC:Live feed of scheduled and posted content."),
    ]
    for post in posts:
        names = sorted(
            {target_map.get(v.target_id, "") for v in post.variants} - {""}
        )
        lines.extend(_event_lines(post, names))
    lines.append("END:VCALENDAR")
    # iCal spec is CRLF-terminated, including after the final END line.
    return "\r\n".join(lines) + "\r\n"


# ---------- Endpoints ----------


@router.get(".ics")
def calendar_feed(
    token: str = Query(default=""),
    db: Session = Depends(get_session),
) -> Response:
    _check_token(token)
    posts = (
        db.query(Post)
        .options(selectinload(Post.variants))
        .filter(
            (Post.scheduled_for.isnot(None)) | (Post.posted_at.isnot(None))
        )
        .order_by(Post.scheduled_for.asc().nullslast())
        .all()
    )
    target_ids = {v.target_id for p in posts for v in p.variants}
    if target_ids:
        targets = db.query(Target).filter(Target.id.in_(target_ids)).all()
        target_map = {t.id: t.name for t in targets}
    else:
        target_map = {}
    body = _render_calendar(posts, target_map)
    return Response(content=body, media_type="text/calendar; charset=utf-8")


@router.get("/subscribe-url")
def subscribe_url() -> dict:
    """Return the URL the user pastes into their calendar app."""
    pin = settings.dashboard_pin.strip()
    if not pin:
        return {"url": "/api/calendar.ics", "auth_required": False}
    return {
        "url": f"/api/calendar.ics?token={make_calendar_token(pin)}",
        "auth_required": True,
    }
