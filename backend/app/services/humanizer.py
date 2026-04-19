"""Humanizer service (M4).

Central place for the "pretend to be a human" logic that lives on the backend:

- `get_or_create_profile()` — singleton access.
- `apply_schedule_jitter(when)` — ±N minutes of random offset on scheduled_for.
- `in_blackout(when)` — returns the BlackoutDate that blocks `when`, if any.
- `on_failure(platform_id, reason)` / `on_success(platform_id)` — adjust
  SessionHealth and, if the failure counter crosses the threshold, activate the
  smart pause.
- `check_pause(now)` — is the system currently paused? Returns the end-time
  of the pause if so.
- `detect_checkpoint(reason)` — classify a variant's error string as a FB
  auth challenge / shadow-ban suspicion / unrelated transient.

All functions are sync (plain Session) so they compose with the existing
synchronous SQLAlchemy setup.
"""
from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import (
    BlackoutDate,
    HumanizerProfile,
    SessionHealth,
    SessionHealthStatus,
)

log = logging.getLogger("services.humanizer")


# Patterns the extension reports when FB shows an auth / captcha screen.
CHECKPOINT_PATTERNS = (
    re.compile(r"checkpoint", re.I),
    re.compile(r"captcha", re.I),
    re.compile(r"re.?enter.*password", re.I),
    re.compile(r"two.?factor|2fa", re.I),
    re.compile(r"\bconfirm your identity\b", re.I),
)

SHADOW_BAN_PATTERNS = (
    re.compile(r"unavailable", re.I),
    re.compile(r"restricted", re.I),
    re.compile(r"temporarily blocked", re.I),
    re.compile(r"violat", re.I),
)


@dataclass
class FailureClassification:
    kind: str  # "checkpoint" | "shadow_ban" | "unknown"
    raw: str


def classify_failure(error: str | None) -> FailureClassification:
    if not error:
        return FailureClassification(kind="unknown", raw="")
    for p in CHECKPOINT_PATTERNS:
        if p.search(error):
            return FailureClassification(kind="checkpoint", raw=error)
    for p in SHADOW_BAN_PATTERNS:
        if p.search(error):
            return FailureClassification(kind="shadow_ban", raw=error)
    return FailureClassification(kind="unknown", raw=error)


def get_or_create_profile(db: Session) -> HumanizerProfile:
    row = db.query(HumanizerProfile).first()
    if row is not None:
        return row
    row = HumanizerProfile()
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def apply_schedule_jitter(when: datetime, profile: HumanizerProfile) -> datetime:
    """Return a new datetime within ±jitter_minutes of `when`.

    Falls back to `when` unchanged when jitter is 0 (useful in tests).
    """
    j = max(0, profile.schedule_jitter_minutes)
    if j == 0:
        return when
    offset_sec = random.randint(-j * 60, j * 60)
    return when + timedelta(seconds=offset_sec)


def in_blackout(db: Session, when: datetime) -> BlackoutDate | None:
    """Return the BlackoutDate covering `when`, if any. We consider it a match if
    the blackout row's date is the same calendar day (UTC)."""
    day_start = when.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    return (
        db.query(BlackoutDate)
        .filter(BlackoutDate.date >= day_start)
        .filter(BlackoutDate.date < day_end)
        .first()
    )


def _get_health(db: Session, platform_id: str) -> SessionHealth:
    row = (
        db.query(SessionHealth)
        .filter(SessionHealth.platform_id == platform_id)
        .first()
    )
    if row is None:
        row = SessionHealth(platform_id=platform_id)
        db.add(row)
        db.flush()
    return row


def on_success(db: Session, platform_id: str) -> SessionHealth:
    health = _get_health(db, platform_id)
    health.consecutive_failures = 0
    health.status = SessionHealthStatus.HEALTHY
    health.last_success_at = datetime.now(UTC)
    db.commit()
    return health


def on_failure(
    db: Session,
    platform_id: str,
    reason: str,
) -> tuple[SessionHealth, HumanizerProfile]:
    """Record a failure. If the counter reaches the threshold OR we detect a
    checkpoint / shadow-ban signal, activate the smart pause."""
    profile = get_or_create_profile(db)
    health = _get_health(db, platform_id)
    health.consecutive_failures += 1
    health.last_failure_at = datetime.now(UTC)
    health.last_failure_reason = reason

    classification = classify_failure(reason)
    if classification.kind == "checkpoint":
        health.status = SessionHealthStatus.CHECKPOINT
        _activate_pause(profile, reason=f"checkpoint detected: {reason[:200]}")
    elif classification.kind == "shadow_ban":
        health.status = SessionHealthStatus.SHADOW_BAN_SUSPECTED
        _activate_pause(profile, reason=f"shadow-ban pattern: {reason[:200]}")
    elif health.consecutive_failures >= profile.consecutive_failures_threshold:
        health.status = SessionHealthStatus.PAUSED
        _activate_pause(
            profile,
            reason=(
                f"{health.consecutive_failures} consecutive failures "
                f"(threshold {profile.consecutive_failures_threshold})"
            ),
        )
    else:
        health.status = SessionHealthStatus.WARNING

    db.commit()
    return health, profile


def _activate_pause(profile: HumanizerProfile, reason: str) -> None:
    profile.smart_pause_until = datetime.now(UTC) + timedelta(
        minutes=profile.smart_pause_minutes
    )
    profile.smart_pause_reason = reason
    log.warning(
        "Smart pause activated: %s (until %s)", reason, profile.smart_pause_until
    )


def check_pause(db: Session, now: datetime | None = None) -> datetime | None:
    """Return the pause end-time if we're currently paused, else None."""
    profile = get_or_create_profile(db)
    now = now or datetime.now(UTC)
    if profile.smart_pause_until is None:
        return None
    pause_until = profile.smart_pause_until
    if pause_until.tzinfo is None:
        pause_until = pause_until.replace(tzinfo=UTC)
    if pause_until > now:
        return pause_until
    # Pause expired — auto-clear.
    profile.smart_pause_until = None
    profile.smart_pause_reason = None
    db.commit()
    return None


def clear_pause(db: Session) -> None:
    profile = get_or_create_profile(db)
    profile.smart_pause_until = None
    profile.smart_pause_reason = None
    db.commit()


def humanizer_config_for_extension(profile: HumanizerProfile) -> dict:
    """Serialize the subset of knobs the extension's content script cares about.

    Kept JSON-friendly so it ships verbatim via the publish command.
    """
    return {
        "typing_wpm_min": profile.typing_wpm_min,
        "typing_wpm_max": profile.typing_wpm_max,
        "mistake_rate": profile.mistake_rate,
        "pause_between_sentences_ms_min": profile.pause_between_sentences_ms_min,
        "pause_between_sentences_ms_max": profile.pause_between_sentences_ms_max,
        "mouse_path_curvature": profile.mouse_path_curvature,
        "idle_scroll_before_post_sec_min": profile.idle_scroll_before_post_sec_min,
        "idle_scroll_before_post_sec_max": profile.idle_scroll_before_post_sec_max,
    }
