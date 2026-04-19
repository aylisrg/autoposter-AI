"""Platform registry — single source of truth for platform dispatch.

Every Target row has a `platform_id` string. The scheduler, metrics service,
and posts API look up the right Platform class here instead of hard-coding
`FacebookPlatform()` everywhere.

Adding a new platform (LinkedIn, X, Telegram, VK) = add it to `PLATFORMS`.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.platforms.base import Platform
from app.platforms.facebook import FacebookPlatform
from app.platforms.instagram import InstagramPlatform
from app.platforms.threads import ThreadsPlatform


# Keys MUST match `Target.platform_id`.
PLATFORMS: dict[str, type[Platform]] = {
    "facebook": FacebookPlatform,
    "instagram": InstagramPlatform,
    "threads": ThreadsPlatform,
}


def get_platform(platform_id: str, db: Session | None = None) -> Platform | None:
    """Return a Platform instance for `platform_id`, or None.

    IG / Threads need a DB session to look up credentials; Facebook ignores
    the parameter. Callers should always pass `db` — it's harmless when the
    platform doesn't use it.
    """
    cls = PLATFORMS.get(platform_id)
    if cls is None:
        return None
    # IG / Threads accept an optional session in their ctor. FacebookPlatform
    # doesn't, so we try both signatures cleanly.
    try:
        return cls(db=db)  # type: ignore[call-arg]
    except TypeError:
        return cls()
