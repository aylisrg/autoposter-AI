"""Shared test fixtures.

- Use an in-memory SQLite per test run — no touching the real data/app.db.
- Stub out the APScheduler in main.lifespan (no background ticks during tests).
- Provide a FastAPI TestClient with the DB dependency pointing at our in-mem engine.
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import session as db_session
from app.db.models import Base


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session_maker(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture()
def db(session_maker) -> Iterator[Session]:
    s = session_maker()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def client(engine, session_maker, monkeypatch) -> Iterator[TestClient]:
    # Swap the module-level SessionLocal that get_session pulls from.
    monkeypatch.setattr(db_session, "engine", engine, raising=True)
    monkeypatch.setattr(db_session, "SessionLocal", session_maker, raising=True)

    # Stub scheduler so lifespan doesn't spawn background jobs.
    from app.scheduler import scheduler as app_scheduler

    monkeypatch.setattr(app_scheduler, "start", lambda: None, raising=False)
    monkeypatch.setattr(app_scheduler, "shutdown", lambda wait=False: None, raising=False)

    # Import app AFTER patches so its dependencies resolve against the test engine.
    from app.main import app

    with TestClient(app) as c:
        yield c
