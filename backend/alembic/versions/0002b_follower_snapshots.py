"""add follower_snapshots

Stores the daily follower-count time series per connected platform account.
Writes are append-only: one row per collection tick per credential.

Revision ID: 0002b
Revises: 0002
Create Date: 2026-04-19 21:35:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002b"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "follower_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("platform_id", sa.String(length=50), nullable=False),
        sa.Column("account_id", sa.String(length=100), nullable=False),
        sa.Column("followers", sa.Integer(), nullable=False),
        sa.Column(
            "collected_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("follower_snapshots", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_follower_snapshots_platform_id"),
            ["platform_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_follower_snapshots_account_id"),
            ["account_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_follower_snapshots_collected_at"),
            ["collected_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("follower_snapshots", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_follower_snapshots_collected_at"))
        batch_op.drop_index(batch_op.f("ix_follower_snapshots_account_id"))
        batch_op.drop_index(batch_op.f("ix_follower_snapshots_platform_id"))
    op.drop_table("follower_snapshots")
