"""Initial schema — meetings, tasks, feedback_corrections.

Revision ID: 0001
Revises:
Create Date: 2026-05-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meetings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("audio_filename", sa.String(255)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("participants", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("summary_text", sa.Text()),
        sa.Column("run_metrics", postgresql.JSONB()),
        sa.Column("error", sa.Text()),
    )
    op.create_index("ix_meetings_status", "meetings", ["status"])
    op.create_index("ix_meetings_created_at", "meetings", ["created_at"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "meeting_id",
            sa.String(36),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_id", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("assignee", sa.String(255)),
        sa.Column("assignee_id", sa.String(100)),
        sa.Column("due_date", sa.Date()),
        sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("extraction_confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column(
            "source_turn_ids", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column("notes", sa.Text()),
        sa.Column("bucket", sa.String(20), nullable=False, server_default="action"),
        sa.UniqueConstraint("meeting_id", "task_id", name="uq_tasks_meeting_task"),
    )
    op.create_index("ix_tasks_meeting_id", "tasks", ["meeting_id"])
    op.create_index("ix_tasks_bucket", "tasks", ["bucket"])

    op.create_table(
        "feedback_corrections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "meeting_id",
            sa.String(36),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_id", sa.String(100)),
        sa.Column("reviewer", sa.String(255)),
        sa.Column("notes", sa.Text()),
        sa.Column("original_description", sa.Text()),
        sa.Column("corrected_description", sa.Text()),
        sa.Column("original_assignee", sa.String(255)),
        sa.Column("corrected_assignee", sa.String(255)),
        sa.Column("original_due_date", sa.Date()),
        sa.Column("corrected_due_date", sa.Date()),
        sa.Column("is_false_positive", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_missing", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_feedback_meeting_id", "feedback_corrections", ["meeting_id"])
    op.create_index("ix_feedback_submitted_at", "feedback_corrections", ["submitted_at"])


def downgrade() -> None:
    op.drop_table("feedback_corrections")
    op.drop_table("tasks")
    op.drop_table("meetings")
