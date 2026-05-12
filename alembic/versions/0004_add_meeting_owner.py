"""Add owner_user_id to meetings.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("owner_user_id", sa.String(length=255), nullable=True))
    op.create_index("ix_meetings_owner_user_id", "meetings", ["owner_user_id"])


def downgrade() -> None:
    op.drop_index("ix_meetings_owner_user_id", table_name="meetings")
    op.drop_column("meetings", "owner_user_id")
