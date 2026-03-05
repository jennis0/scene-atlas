"""Add job_warnings and total_file_size columns to import_jobs.

These columns support the ingest error reporting feature:
- job_warnings: JSON list of warning dicts (upload-phase skips, pipeline warnings)
- total_file_size: accumulated bytes across all upload batches

Revision ID: 017
Revises: 016
"""

import sqlalchemy as sa
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("import_jobs", sa.Column("job_warnings", sa.Text(), nullable=True))
    op.add_column(
        "import_jobs", sa.Column("total_file_size", sa.Integer(), server_default="0", nullable=True)
    )


def downgrade() -> None:
    op.drop_column("import_jobs", "total_file_size")
    op.drop_column("import_jobs", "job_warnings")
