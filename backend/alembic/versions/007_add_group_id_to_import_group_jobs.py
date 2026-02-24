"""Add created_group_id to import_group_jobs to link completed groups back to their ImageGroup.

Revision ID: 007
Revises: 006
Create Date: 2026-02-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "import_group_jobs",
        sa.Column("created_group_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("import_group_jobs", "created_group_id")
