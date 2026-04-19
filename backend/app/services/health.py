"""Gauge samplers for /metrics.

Each `sample_*` function is called on every Prometheus scrape and returns a
list of `(gauge_name, labels, value)` tuples. Samplers must be defensive —
errors are logged in `observability._sampled_gauges` but the scrape still
succeeds. Keep each one cheap (a single indexed query at most).

Gauges:
- autoposter_extension_connected       — 0/1, is the WS bridge attached
- autoposter_backup_age_seconds        — age of the newest .zip in backup_dir
                                          (or -1 if no backups yet)
- autoposter_scheduler_due_posts       — SCHEDULED posts whose time has passed
- autoposter_pending_review_posts      — PENDING_REVIEW queue depth
"""
from __future__ import annotations

import glob
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func

from app.config import settings
from app.db import session as db_session
from app.db.models import Post, PostStatus
from app.observability import GaugeSample
from app.ws.extension_bridge import bridge

log = logging.getLogger("health")


def sample_extension_status() -> list[GaugeSample]:
    return [("autoposter_extension_connected", {}, 1.0 if bridge.connected else 0.0)]


def sample_backup_age() -> list[GaugeSample]:
    backup_dir = Path(settings.backup_dir)
    if not backup_dir.exists():
        return [("autoposter_backup_age_seconds", {}, -1.0)]
    zips = glob.glob(str(backup_dir / "*.zip"))
    if not zips:
        return [("autoposter_backup_age_seconds", {}, -1.0)]
    newest = max(os.path.getmtime(p) for p in zips)
    age = max(0.0, time.time() - newest)
    return [("autoposter_backup_age_seconds", {}, age)]


def sample_scheduler_depth() -> list[GaugeSample]:
    """Count SCHEDULED posts due now, plus PENDING_REVIEW backlog."""
    now = datetime.now(UTC)
    # Late-bind SessionLocal so tests that monkeypatch it are respected.
    db = db_session.SessionLocal()
    try:
        due = (
            db.query(func.count(Post.id))
            .filter(Post.status == PostStatus.SCHEDULED)
            .filter(Post.scheduled_for.isnot(None))
            .filter(Post.scheduled_for <= now)
            .scalar()
            or 0
        )
        pending = (
            db.query(func.count(Post.id))
            .filter(Post.status == PostStatus.PENDING_REVIEW)
            .scalar()
            or 0
        )
        return [
            ("autoposter_scheduler_due_posts", {}, float(due)),
            ("autoposter_pending_review_posts", {}, float(pending)),
        ]
    finally:
        db.close()
