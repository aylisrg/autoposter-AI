"""add post_variants.ab_arm

Used by the A/B-split endpoint to tag each variant with the arm it was
assigned to so metrics can be aggregated by arm afterwards.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-19 21:05:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("post_variants", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ab_arm", sa.String(length=50), nullable=True))
        batch_op.create_index(batch_op.f("ix_post_variants_ab_arm"), ["ab_arm"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("post_variants", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_post_variants_ab_arm"))
        batch_op.drop_column("ab_arm")
