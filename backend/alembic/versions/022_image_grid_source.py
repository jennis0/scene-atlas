"""Record where each image's grid information came from.

Adds ``images.grid_source``: ``filename`` (parsed from the file name), ``detector``
(image analysis) or ``user`` (edited by hand). Grid re-detection never overwrites
``user`` values. Existing rows are labelled from what's known: a confidence means the
detector set it; otherwise any grid information came from the file name.

Revision ID: 022
Revises: 021
"""

import sqlalchemy as sa
from alembic import op

revision = "022"
down_revision = "021"


def upgrade():
    op.add_column("images", sa.Column("grid_source", sa.String(), nullable=True))
    op.execute("UPDATE images SET grid_source = 'detector' WHERE grid_confidence IS NOT NULL")
    op.execute(
        "UPDATE images SET grid_source = 'filename' "
        "WHERE grid_source IS NULL AND (gridded IS NOT NULL OR grid_width IS NOT NULL)"
    )


def downgrade():
    with op.batch_alter_table("images") as batch:
        batch.drop_column("grid_source")
