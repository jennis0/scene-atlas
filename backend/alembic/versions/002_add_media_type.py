"""Add media_type column to images table.

Revision ID: 002
Revises: 001
Create Date: 2026-02-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "images",
        sa.Column("media_type", sa.String(), nullable=True, server_default="image"),
    )
    op.execute("UPDATE images SET media_type = 'image' WHERE media_type IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("images") as batch_op:
        batch_op.drop_column("media_type")
