"""Database session factory. Sync for simplicity — we're local, low-volume."""
import time
from pathlib import Path
from threading import Lock

from fastapi import Depends
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.models import Base, BusinessProfile

# Ensure data dir exists for SQLite
if settings.db_url.startswith("sqlite"):
    db_path = settings.db_url.replace("sqlite:///", "")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(settings.db_url, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


# SQLite: WAL lets readers and writers run concurrently (default `DELETE` mode
# serializes everything through one lock). `synchronous=NORMAL` pairs with WAL
# and is safe for our single-host workload — we lose only the last ~200 ms of
# writes on OS crash, never corruption. `foreign_keys=ON` enforces the FKs we
# declared; SQLite ignores them by default.
@event.listens_for(engine, "connect")
def _sqlite_pragma(dbapi_conn, _conn_record):
    if not settings.db_url.startswith("sqlite"):
        return
    # In-memory SQLite (":memory:" / "sqlite://") doesn't support WAL.
    is_memory = settings.db_url in ("sqlite://", "sqlite:///:memory:")
    cur = dbapi_conn.cursor()
    try:
        if not is_memory:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
    finally:
        cur.close()


def init_db() -> None:
    """Create tables if they don't exist. For v1, no Alembic — just create_all."""
    Base.metadata.create_all(engine)


def get_session() -> Session:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------- BusinessProfile cache ----------
#
# Every /api/* request used to do `db.query(BusinessProfile).order_by(id).first()`
# — about 14 call sites. We cache the PK for 60 s so follow-up requests do a
# cheap `db.get()` (hits the session identity map or a primary-key index)
# instead of an ORDER BY scan. The cache holds the ID only, NOT the ORM
# object, so we don't fight with session lifetimes.

_PROFILE_CACHE_TTL = 60.0
_profile_cache_id: int | None = None
_profile_cache_at: float = 0.0
_profile_cache_lock = Lock()


def _load_current_profile(db: Session) -> BusinessProfile | None:
    """Do the full ORDER BY query and refresh the cache."""
    global _profile_cache_id, _profile_cache_at
    profile = (
        db.query(BusinessProfile).order_by(BusinessProfile.id.asc()).first()
    )
    with _profile_cache_lock:
        _profile_cache_id = profile.id if profile is not None else None
        _profile_cache_at = time.monotonic()
    return profile


def get_current_profile(db: Session = Depends(get_session)) -> BusinessProfile | None:
    """Return the single BusinessProfile row, or None if none exists.

    Usable as a FastAPI dependency (`profile: BusinessProfile | None = Depends(...)`)
    or called directly with a session. Profile lookups hit a 60-second PK
    cache to avoid repeated ORDER BY scans.
    """
    now = time.monotonic()
    with _profile_cache_lock:
        cached_id = _profile_cache_id
        fresh = cached_id is not None and now - _profile_cache_at < _PROFILE_CACHE_TTL
    if fresh:
        hit = db.get(BusinessProfile, cached_id)
        if hit is not None:
            return hit
        # Row disappeared under us — fall through to reload.
    return _load_current_profile(db)


def invalidate_profile_cache() -> None:
    """Clear the cached ID — call after creating / patching the profile."""
    global _profile_cache_id, _profile_cache_at
    with _profile_cache_lock:
        _profile_cache_id = None
        _profile_cache_at = 0.0
