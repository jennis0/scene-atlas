"""Auto image type on import (ADR-020, design/ingestion.md §5.6).

Adds ``import_items.classification`` (JSON: the image-type head's verdict for Auto
items) and ``import_items.preview_key`` (a small preview in the job's staging folder,
kept for items Auto sorted out so the user can check them before including them), and
indexes for the group editor's sorted-out queries, which go from a gallery group to its
import groups and their skipped items.

Revision ID: 027
Revises: 026
"""

import sqlalchemy as sa
from alembic import op

revision = "027"
down_revision = "026"


def upgrade():
    op.add_column("import_items", sa.Column("classification", sa.Text(), nullable=True))
    op.add_column("import_items", sa.Column("preview_key", sa.String(), nullable=True))
    op.create_index("ix_import_groups_image_group", "import_groups", ["image_group_id"])
    op.create_index("ix_import_items_group_state", "import_items", ["import_group_id", "state"])


def downgrade():
    op.drop_index("ix_import_items_group_state", table_name="import_items")
    op.drop_index("ix_import_groups_image_group", table_name="import_groups")
    with op.batch_alter_table("import_items") as batch:
        batch.drop_column("preview_key")
        batch.drop_column("classification")
