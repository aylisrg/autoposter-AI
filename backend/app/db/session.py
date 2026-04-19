"""Database session factory. Sync for simplicity — we're local, low-volume."""
import logging
import time
from pathlib import Path
from threading import Lock

from fastapi import Depends
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.models import Base, BusinessProfile

log = logging.getLogger(__name__)

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


_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _alembic_config():
    """Build an Alembic Config pointing at `backend/alembic.ini`.

    We pass the already-built `engine` via `config.attributes` so migrations
    execute on the same Connection the app uses. That's essential for
    in-memory SQLite and for tests that monkeypatch `engine` — spawning a
    fresh engine from the URL would target a different (empty) database.
    """
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(_ALEMBIC_INI))
    cfg.attributes["engine"] = engine
    return cfg


def init_db() -> None:
    """Bring the schema up to `head` via Alembic.

    Two paths:

    - Fresh DB (no tables, or only the `alembic_version` table): run
      ``upgrade head`` which applies every revision from 0001.
    - Pre-Alembic DB (tables exist but `alembic_version` is missing):
      the schema was created by an earlier `Base.metadata.create_all` build.
      We ``stamp head`` instead — the tables match `head` already; rerunning
      all CREATE TABLEs would fail on "table already exists". Subsequent
      boots will see `alembic_version` and take the upgrade path for any
      new revisions.
    """
    from alembic import command

    cfg = _alembic_config()

    insp = inspect(engine)
    existing = set(insp.get_table_names())
    if existing and "alembic_version" not in existing:
        log.info("init_db: pre-Alembic schema detected, stamping head")
        command.stamp(cfg, "head")
    else:
        command.upgrade(cfg, "head")


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
