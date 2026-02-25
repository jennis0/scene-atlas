"""Add import job lifecycle columns: analysis_result, updated_at, all_confirmed.

Migrates existing 'running' status to 'active' to reflect the new lifecycle.

Revision ID: 009
Revises: 008
Create Date: 2026-02-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # New columns on import_jobs
    op.add_column("import_jobs", sa.Column("analysis_result", sa.Text(), nullable=True))
    op.add_column("import_jobs", sa.Column("updated_at", sa.DateTime(), nullable=True))
    op.add_column(
        "import_jobs", sa.Column("all_confirmed", sa.Boolean(), server_default="0", nullable=False)
    )

    # Migrate existing 'running' status → 'active'
    op.execute("UPDATE import_jobs SET status = 'active' WHERE status = 'running'")

    # Backfill updated_at from created_at for existing rows
    op.execute("UPDATE import_jobs SET updated_at = created_at WHERE updated_at IS NULL")


def downgrade() -> None:
    # Revert status back
    op.execute("UPDATE import_jobs SET status = 'running' WHERE status = 'active'")

    op.drop_column("import_jobs", "all_confirmed")
    op.drop_column("import_jobs", "updated_at")
    op.drop_column("import_jobs", "analysis_result")
