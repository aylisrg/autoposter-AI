"""Alembic environment.

Pulls the DB URL from `app.config.settings` so we don't duplicate config in
alembic.ini. Target metadata is the app's SQLAlchemy `Base.metadata`, which
means `alembic revision --autogenerate` sees the same models the app does.

SQLite nuance: when the URL points at SQLite we enable `render_as_batch=True`
so column-level ALTER operations (which SQLite doesn't support natively) get
emitted as batched recreate-the-table migrations. Without this, autogenerate
produces ops that silently no-op on SQLite.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the URL at runtime. .env (via pydantic-settings) is the source of truth.
config.set_main_option("sqlalchemy.url", settings.db_url)

target_metadata = Base.metadata


def _is_sqlite() -> bool:
    return settings.db_url.startswith("sqlite")


def run_migrations_offline() -> None:
    """Generate SQL without connecting. Useful for writing out a migration
    script for a DBA to review.
    """
    context.configure(
        url=settings.db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_is_sqlite(),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run against a live engine. This is the code path `alembic upgrade`
    takes and the one `init_db()` triggers at startup.

    When invoked programmatically from `init_db()` (or a test), the caller
    stashes the already-built engine in ``config.attributes["engine"]`` so
    migrations run against the same connection the app uses. That matters
    for in-memory SQLite, where a fresh engine would be a separate DB.
    """
    connectable = config.attributes.get("engine")
    if connectable is None:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_is_sqlite(),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
