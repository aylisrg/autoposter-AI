"""Phase 4 — Alembic migrations.

Covers `init_db()`'s two-path contract:

- Fresh DB: `upgrade head` runs every revision, creating every model table.
- Pre-Alembic DB: `create_all`-style schema is `stamp`ed at head instead of
  re-upgraded. This is the backwards-compat path for users who ran the app
  before Alembic was introduced.

We also verify idempotency — calling `init_db` twice on the same engine is
a no-op the second time.
"""
from __future__ import annotations

from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from app.db import session as db_session
from app.db.models import Base


def _head_revision() -> str:
    """Ask Alembic what `head` currently is instead of hard-coding a revision
    id that drifts every time we add a migration."""
    return ScriptDirectory.from_config(db_session._alembic_config()).get_current_head()

# Tables the baseline migration 0001 is expected to create. Keep this list
# explicit so drift in the model layer or a botched autogen gets caught
# here instead of at deploy time.
_BASELINE_TABLES = {
    "analyst_reports",
    "blackout_dates",
    "business_profile",
    "content_plans",
    "feedback",
    "few_shot_examples",
    "humanizer_profiles",
    "logs",
    "media_assets",
    "optimizer_proposals",
    "plan_slots",
    "platform_credentials",
    "post_metrics",
    "post_variants",
    "posts",
    "session_health",
    "targets",
}


def _fresh_engine():
    """A shared-cache in-memory SQLite — StaticPool keeps the same connection
    across `.connect()` calls so Alembic's bookkeeping survives."""
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )


def test_init_db_upgrades_fresh_db(monkeypatch):
    eng = _fresh_engine()
    monkeypatch.setattr(db_session, "engine", eng, raising=True)

    db_session.init_db()

    existing = set(inspect(eng).get_table_names())
    missing = _BASELINE_TABLES - existing
    assert not missing, f"baseline migration did not create: {missing}"
    assert "alembic_version" in existing

    with eng.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
    assert row is not None and row[0] == _head_revision()


def test_init_db_is_idempotent(monkeypatch):
    eng = _fresh_engine()
    monkeypatch.setattr(db_session, "engine", eng, raising=True)

    db_session.init_db()
    # Second call must not raise — `upgrade head` when already at head is a
    # no-op in Alembic.
    db_session.init_db()

    with eng.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
    assert row[0] == _head_revision()


def test_init_db_stamps_preexisting_schema(monkeypatch):
    """Simulate a DB populated by the pre-Alembic `create_all` path.

    Tables exist, `alembic_version` does not. init_db must mark the schema
    as head rather than re-run CREATE TABLEs (which would fail).
    """
    eng = _fresh_engine()
    Base.metadata.create_all(eng)

    tables_before = set(inspect(eng).get_table_names())
    assert "alembic_version" not in tables_before
    assert "posts" in tables_before  # sanity — create_all worked

    monkeypatch.setattr(db_session, "engine", eng, raising=True)
    db_session.init_db()

    tables_after = set(inspect(eng).get_table_names())
    assert "alembic_version" in tables_after

    with eng.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
    assert row[0] == _head_revision()


def test_alembic_config_points_at_bundled_ini():
    """Guard against a stale path if `session.py` moves relative to alembic.ini."""
    assert db_session._ALEMBIC_INI.exists()
    assert db_session._ALEMBIC_INI.name == "alembic.ini"
