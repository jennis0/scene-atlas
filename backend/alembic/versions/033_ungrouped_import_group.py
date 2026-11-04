"""An import's ungrouped files (design/variant-grouping.md §3).

- ``import_groups.ungrouped``: the job's one group of files that made no image (sorted out by
  Auto, failed, duplicates) and belong to no map group by folder or name. Such files take no
  part in grouping; they are kept here so the review can show them.

Existing import groups are ordinary groups.

Revision ID: 033
Revises: 032
"""

import sqlalchemy as sa
from alembic import op

revision = "033"
down_revision = "032"


def upgrade():
    op.add_column(
        "import_groups",
        sa.Column("ungrouped", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("import_groups", "ungrouped")
