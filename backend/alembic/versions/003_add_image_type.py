"""Add image_type column to images table.

Revision ID: 003
Revises: 002
Create Date: 2026-02-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "images",
        sa.Column("image_type", sa.String(), nullable=True, server_default="battlemap"),
    )
    op.execute("UPDATE images SET image_type = 'battlemap' WHERE image_type IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("images") as batch_op:
        batch_op.drop_column("image_type")
