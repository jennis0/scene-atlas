"""Auto image type on import (ADR-020, design/ingestion.md §5.6).

Adds ``import_items.classification`` (JSON: the image-type head's verdict for Auto
items) and ``import_items.preview_key`` (a small preview in the job's staging folder,
kept for items Auto sorted out so the user can check them before including them).

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


def downgrade():
    with op.batch_alter_table("import_items") as batch:
        batch.drop_column("preview_key")
        batch.drop_column("classification")
