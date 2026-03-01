"""Add file_errors column to import_group_jobs.

Stores per-file error details as a JSON-encoded list so the API can
report which images failed and why during an import group.

Revision ID: 012
Revises: 011
Create Date: 2026-03-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("import_group_jobs", sa.Column("file_errors", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("import_group_jobs", "file_errors")
