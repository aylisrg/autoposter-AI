"""Background refresh of Meta long-lived tokens.

Meta long-lived tokens expire ~60 days after issue. The official refresh path
is to call `fb_exchange_token` again with the existing long-lived token — the
response is a brand-new 60-day token. We do this in a daily scheduler tick
for every credential whose `token_expires_at` falls inside a warning window
(default 7 days), so the user is never caught with a silently-dead token.

Tokens without `token_expires_at` (legacy rows from before the OAuth flow
persisted expiry) are skipped — no way to tell if they need refresh. The
user can force-refresh manually via the API/dashboard.

Failures are logged but don't raise: one bad credential shouldn't stop the
tick from processing the rest.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import PlatformCredential
from app.platforms import meta_graph
from app.services.audit import audit_event

log = logging.getLogger("services.token_refresh")


# Platforms this refresher handles. LinkedIn is excluded because its
# refresh-token program is opt-in and handled separately when we enroll.
_META_PLATFORMS = ("instagram", "threads")


@dataclass
class RefreshResult:
    refreshed: int
    skipped: int
    failed: int
    failures: list[str]


def _expires_at_from_payload(payload: dict) -> datetime | None:
    expires_in = payload.get("expires_in")
    if not expires_in:
        return None
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return datetime.now(UTC) + timedelta(seconds=seconds)


def refresh_one(db: Session, credential: PlatformCredential) -> PlatformCredential:
    """Force-refresh a single credential. Raises on failure so callers can 4xx."""
    if credential.platform_id not in _META_PLATFORMS:
        raise ValueError(f"Refresh not supported for platform {credential.platform_id}")
    if not settings.meta_app_id or not settings.meta_app_secret:
        raise RuntimeError("META_APP_ID / META_APP_SECRET must be set to refresh tokens")

    payload = meta_graph.long_lived_token(
        app_id=settings.meta_app_id,
        app_secret=settings.meta_app_secret,
        short_token=credential.access_token,
    )
    credential.access_token = payload["access_token"]
    credential.token_expires_at = _expires_at_from_payload(payload)
    db.commit()
    db.refresh(credential)
    audit_event(
        "refreshed",
        "platform_credential",
        credential_id=credential.id,
        platform_id=credential.platform_id,
        account_id=credential.account_id,
        new_expires_at=credential.token_expires_at.isoformat()
        if credential.token_expires_at
        else None,
    )
    log.info(
        "Refreshed %s credential %d (new expiry: %s)",
        credential.platform_id,
        credential.id,
        credential.token_expires_at,
    )
    return credential


def refresh_expiring(
    db: Session,
    *,
    window_days: int = 7,
    now: datetime | None = None,
) -> RefreshResult:
    """Refresh every credential whose token expires within `window_days`.

    Safe to call whenever — credentials already far from expiry are skipped,
    credentials without an `token_expires_at` are skipped (we can't tell).
    """
    now = now or datetime.now(UTC)
    cutoff = now + timedelta(days=window_days)

    rows = (
        db.query(PlatformCredential)
        .filter(PlatformCredential.platform_id.in_(_META_PLATFORMS))
        .filter(PlatformCredential.token_expires_at.isnot(None))
        .filter(PlatformCredential.token_expires_at <= cutoff)
        .all()
    )

    refreshed = 0
    failed = 0
    failures: list[str] = []
    for row in rows:
        try:
            refresh_one(db, row)
            refreshed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            failures.append(f"{row.platform_id}/{row.account_id}: {exc}")
            log.warning(
                "Failed to refresh %s/%s: %s",
                row.platform_id,
                row.account_id,
                exc,
            )

    return RefreshResult(
        refreshed=refreshed,
        skipped=0,
        failed=failed,
        failures=failures,
    )
