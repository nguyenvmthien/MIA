"""Add transcript turns and meeting artifacts.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transcript_turns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("meeting_id", sa.String(length=36), nullable=False),
        sa.Column("turn_id", sa.String(length=100), nullable=False),
        sa.Column("speaker_id", sa.String(length=100), nullable=False),
        sa.Column("speaker_name", sa.String(length=255), nullable=True),
        sa.Column("worker_id", sa.String(length=100), nullable=True),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("asr_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id", "turn_id", name="uq_transcript_turns_meeting_turn"),
    )
    op.create_index("ix_transcript_turns_meeting_id", "transcript_turns", ["meeting_id"])

    op.create_table(
        "meeting_artifacts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("meeting_id", sa.String(length=36), nullable=False),
        sa.Column("artifact_type", sa.String(length=80), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=True),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("artifact_metadata", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meeting_artifacts_meeting_id", "meeting_artifacts", ["meeting_id"])
    op.create_index("ix_meeting_artifacts_type", "meeting_artifacts", ["artifact_type"])


def downgrade() -> None:
    op.drop_index("ix_meeting_artifacts_type", table_name="meeting_artifacts")
    op.drop_index("ix_meeting_artifacts_meeting_id", table_name="meeting_artifacts")
    op.drop_table("meeting_artifacts")
    op.drop_index("ix_transcript_turns_meeting_id", table_name="transcript_turns")
    op.drop_table("transcript_turns")
