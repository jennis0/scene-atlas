"""Local imports: items read from a path on this computer (design/local-ingest.md).

Adds ``import_items.source_path`` (the original file, read by the worker instead of a
staged upload) and ``import_jobs.source_roots`` (JSON list of the folders a local import
reads from, for availability checks).

Revision ID: 025
Revises: 024
"""

import sqlalchemy as sa
from alembic import op

revision = "025"
down_revision = "024"


def upgrade():
    op.add_column("import_items", sa.Column("source_path", sa.Text(), nullable=True))
    op.add_column("import_jobs", sa.Column("source_roots", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("import_items") as batch:
        batch.drop_column("source_path")
    with op.batch_alter_table("import_jobs") as batch:
        batch.drop_column("source_roots")
