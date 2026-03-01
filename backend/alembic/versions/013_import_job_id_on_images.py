"""Add import_job_id to images table for cancel-with-cleanup tracking.

Stores the import job that created each Image row, so cancel-with-cleanup
can find and delete only the images that belong to a given import.
Duplicate images (same storage_key) are handled by checking sibling count
before deleting physical files.

Revision ID: 013
Revises: 012
Create Date: 2026-03-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("images", sa.Column("import_job_id", sa.String(), nullable=True))
    op.create_index("ix_images_import_job_id", "images", ["import_job_id"])


def downgrade() -> None:
    op.drop_index("ix_images_import_job_id", table_name="images")
    op.drop_column("images", "import_job_id")
