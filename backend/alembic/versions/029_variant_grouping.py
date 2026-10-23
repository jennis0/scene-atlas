"""Variant grouping v2 (ADR-028, design/variant-grouping.md).

- ``image_grouping_features``: per-image content features (a 256-bit pHash and a 32×32
  edge map), written by the ingest worker. Images imported before this have no row.
- ``import_jobs.grouped_at``: when the job's grouping phase grouped its images. A sealed
  job with nothing open and no ``grouped_at`` is in the grouping phase (status
  ``grouping``).
- ``images.awaiting_grouping``: an image committed by an import that hasn't grouped it yet;
  listed nowhere until then. Partial indexes over the listed images (``WHERE
  awaiting_grouping = 0``) keep the facet, browse and count queries on covering indexes
  (on 50k images the facets took 511 ms with the predicate and no such index, 180 ms with).

Existing imports are already grouped (by the old parser, at seal): every sealed job with
nothing open is stamped ``grouped_at``, so none enters the grouping phase and its groups
stay as they are. One still running is left unstamped: its remaining images commit
ungrouped, and when it finishes its grouping phase puts them in the groups its seal
planned. Existing images are not awaiting grouping.

The columns are plain ``ADD COLUMN``s, not table rebuilds, so the triggers on images
(full-text index, group image counts) are untouched.

Revision ID: 029
Revises: 028
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

# Frozen copy of models.database.LISTED_IMAGE_INDEXES as of this migration
LISTED_IMAGE_INDEXES = {
    "ix_images_listed_id": ("id",),
    "ix_images_listed_author": ("author",),
    "ix_images_listed_grid": ("gridded", "grid_type"),
    "ix_images_listed_type": ("image_type",),
    "ix_images_listed_media": ("media_type",),
    "ix_images_listed_created": ("created_at",),
}

revision = "029"
down_revision = "028"


def upgrade():
    op.create_table(
        "image_grouping_features",
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.SmallInteger(), nullable=False),
        sa.Column("phash256", sa.LargeBinary(32), nullable=True),
        sa.Column("edge", sa.LargeBinary(2048), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"]),
        sa.PrimaryKeyConstraint("image_id"),
    )
    op.add_column("import_jobs", sa.Column("grouped_at", sa.DateTime(), nullable=True))
    op.add_column(
        "images",
        sa.Column("awaiting_grouping", sa.Boolean(), nullable=False, server_default="0"),
    )
    for name, columns in LISTED_IMAGE_INDEXES.items():
        op.create_index(
            name, "images", list(columns), sqlite_where=sa.text("awaiting_grouping = 0")
        )
    now = datetime.now(UTC).replace(tzinfo=None)
    op.get_bind().execute(
        sa.text(
            "UPDATE import_jobs SET grouped_at = COALESCE(completed_at, :now) "
            "WHERE planned_at IS NOT NULL AND NOT EXISTS (SELECT 1 FROM import_items "
            "WHERE import_items.job_id = import_jobs.id "
            "AND import_items.state IN ('awaiting_bytes', 'ready', 'processing'))"
        ).bindparams(sa.bindparam("now", now, type_=sa.DateTime()))
    )


def downgrade():
    # SQLite's native DROP COLUMN (3.35+), as migrations 014 and 018 use: no rebuild
    for name in LISTED_IMAGE_INDEXES:
        op.drop_index(name, table_name="images")
    op.drop_column("images", "awaiting_grouping")
    op.drop_column("import_jobs", "grouped_at")
    op.drop_table("image_grouping_features")
