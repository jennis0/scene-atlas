"""Orient grid sizes taken from file names to match their image.

File names disagree on whether "30x20" means columns x rows or rows x columns, and
ingest stored the numbers in name order. ``grid_width`` is the column count, so a
portrait map named "30x20" was stored as 30 columns of very tall cells. Ingest now
orients the pair (``backend.pipeline.ingest_process.orient_grid``); this swaps the
existing rows it would have swapped. The rule is copied here because migrations
must not import app code.

Only exact file-name sizes change (``grid_source = 'filename'`` with no confidence).
Detected sizes are measured per axis, and grids set by hand are the user's. Images
within 2% of square keep the name's order.

The downgrade is a no-op: which rows were swapped is not recorded.

Revision ID: 026
Revises: 025
"""

from alembic import op

revision = "026"
down_revision = "025"


def upgrade():
    op.execute(
        """
        UPDATE images
        SET grid_width = grid_height, grid_height = grid_width
        WHERE grid_source = 'filename'
          AND grid_confidence IS NULL
          AND grid_width IS NOT NULL AND grid_height IS NOT NULL
          AND width IS NOT NULL AND height IS NOT NULL
          AND ABS(width - height) * 50 > CASE WHEN width > height THEN width ELSE height END
          AND (grid_width > grid_height) <> (width > height)
        """
    )


def downgrade():
    pass
