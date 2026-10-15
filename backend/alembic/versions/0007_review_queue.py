"""add review_queue_items table

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-16 05:20:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_queue_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("pending", "approved", "edited", "rejected", name="reviewqueuestatus"), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewer_action", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_queue_items_post_id", "review_queue_items", ["post_id"])


def downgrade() -> None:
    op.drop_index("ix_review_queue_items_post_id", table_name="review_queue_items")
    op.drop_table("review_queue_items")
