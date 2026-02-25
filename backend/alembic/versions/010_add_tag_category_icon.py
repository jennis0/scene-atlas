"""Add icon column to tag_categories.

Revision ID: 010
Revises: 009
Create Date: 2026-02-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tag_categories", sa.Column("icon", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("tag_categories", "icon")
