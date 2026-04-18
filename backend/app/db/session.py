"""Database session factory. Sync for simplicity — we're local, low-volume."""
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.models import Base

# Ensure data dir exists for SQLite
if settings.db_url.startswith("sqlite"):
    db_path = settings.db_url.replace("sqlite:///", "")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(settings.db_url, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


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
