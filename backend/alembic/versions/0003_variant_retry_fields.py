"""add post_variants.attempt_count + next_retry_at

Needed by the scheduler retry loop (Phase 6b). `attempt_count` lets the
publisher cap retries at 3; `next_retry_at` is how we defer the retry — the
publish tick filters on `next_retry_at IS NULL OR next_retry_at <= now()`.

Revision ID: 0003
Revises: 0002b
Create Date: 2026-04-20 09:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: Union[str, None] = "0002b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("post_variants", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "attempt_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column("next_retry_at", sa.DateTime(), nullable=True)
        )
        batch_op.create_index(
            batch_op.f("ix_post_variants_next_retry_at"),
            ["next_retry_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("post_variants", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_post_variants_next_retry_at"))
        batch_op.drop_column("next_retry_at")
        batch_op.drop_column("attempt_count")
