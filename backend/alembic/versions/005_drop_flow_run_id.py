"""Drop unused flow_run_id column from import_group_jobs.

This column was used to link to Prefect flow runs, which have been replaced
by the in-process JobRunner.

Revision ID: 005
Revises: 004
Create Date: 2026-02-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("import_group_jobs") as batch_op:
        batch_op.drop_column("flow_run_id")


def downgrade() -> None:
    op.add_column(
        "import_group_jobs",
        sa.Column("flow_run_id", sa.String(), nullable=True),
    )
