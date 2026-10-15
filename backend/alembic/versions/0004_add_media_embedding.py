"""add media_assets.embedding

Stores the local (or voyage/BGE) embedding of caption+tags as a JSON list of floats.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15 09:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("media_assets", schema=None) as batch_op:
        batch_op.add_column(sa.Column("embedding", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("media_assets", schema=None) as batch_op:
        batch_op.drop_column("embedding")
