"""Add meeting_participants table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meeting_participants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "meeting_id",
            sa.String(36),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("speaker_id", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("worker_id", sa.String(100)),
        sa.Column("email", sa.String(255)),
        sa.UniqueConstraint("meeting_id", "speaker_id", name="uq_participants_meeting_speaker"),
    )
    op.create_index("ix_participants_meeting_id", "meeting_participants", ["meeting_id"])
    op.create_index("ix_participants_worker_id", "meeting_participants", ["worker_id"])


def downgrade() -> None:
    op.drop_table("meeting_participants")
