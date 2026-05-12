"""Add workers table.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("worker_id", sa.String(length=100), nullable=False),
        sa.Column("owner_user_id", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=255), nullable=True),
        sa.Column("aliases", JSONB(), nullable=False),
        sa.Column("skills", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id", "worker_id", name="uq_workers_owner_worker"),
    )
    op.create_index("ix_workers_owner_user_id", "workers", ["owner_user_id"])
    op.create_index("ix_workers_name", "workers", ["name"])


def downgrade() -> None:
    op.drop_index("ix_workers_name", table_name="workers")
    op.drop_index("ix_workers_owner_user_id", table_name="workers")
    op.drop_table("workers")
