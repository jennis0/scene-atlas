"""Add index on images.created_at for sort-by-date queries.

Revision ID: 006
Revises: 005
Create Date: 2026-02-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_images_created_at", "images", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_images_created_at", table_name="images")
