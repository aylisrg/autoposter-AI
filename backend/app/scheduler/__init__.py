"""Scheduler singleton. APScheduler AsyncIO flavour — runs inside the FastAPI loop.

Lifecycle (see main.py lifespan):
    scheduler.start()        # on app startup
    scheduler.shutdown(...)  # on app shutdown

Tick job: `publish_due_posts` runs every 30 s, looks at Posts where status=SCHEDULED
and scheduled_for <= now, and publishes them through the Facebook platform.
"""
from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

log = logging.getLogger("scheduler")


class SchedulerSingleton:
    def __init__(self) -> None:
        self._impl: AsyncIOScheduler | None = None

    def is_running(self) -> bool:
        return self._impl is not None and self._impl.running

    def start(self) -> None:
        if self.is_running():
            log.warning("Scheduler already running; skipping start")
            return
        # Late import: jobs.py imports models, which require db init first.
        from app.scheduler.jobs import (
            collect_metrics_tick,
            daily_backup_tick,
            publish_due_posts,
            weekly_analyst_tick,
        )

        self._impl = AsyncIOScheduler(timezone="UTC")
        self._impl.add_job(
            publish_due_posts,
            trigger="interval",
            seconds=30,
            id="publish_due_posts",
            coalesce=True,
            max_instances=1,
            next_run_time=datetime.utcnow(),
        )
        # Metrics collection (M6) — hourly, best effort.
        self._impl.add_job(
            collect_metrics_tick,
            trigger="interval",
            hours=1,
            id="collect_metrics",
            coalesce=True,
            max_instances=1,
        )
        # Weekly Analyst (M6) — Sundays at 21:00 UTC. A no-op if profile or
        # metrics are missing.
        self._impl.add_job(
            weekly_analyst_tick,
            trigger="cron",
            day_of_week="sun",
            hour=21,
            minute=0,
            id="weekly_analyst",
            coalesce=True,
            max_instances=1,
        )
        # Daily backup (M8) — 03:00 UTC.
        self._impl.add_job(
            daily_backup_tick,
            trigger="cron",
            hour=3,
            minute=0,
            id="daily_backup",
            coalesce=True,
            max_instances=1,
        )
        self._impl.start()
        log.info(
            "Scheduler started (publish 30s, metrics 1h, analyst Sun 21:00, backup 03:00)"
        )

    def shutdown(self, wait: bool = False) -> None:
        if self._impl is None:
            return
        try:
            self._impl.shutdown(wait=wait)
        except Exception as exc:  # noqa: BLE001
            log.warning("Scheduler shutdown error: %s", exc)
        self._impl = None
        log.info("Scheduler stopped")


scheduler = SchedulerSingleton()

__all__ = ["scheduler"]
