"""Add transcript column to meetings table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # transcript_turns: raw speaker turns as JSONB for fine-tuning input
    from sqlalchemy.dialects.postgresql import JSONB
    op.add_column("meetings", sa.Column("transcript_turns", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("meetings", "transcript_turns")
