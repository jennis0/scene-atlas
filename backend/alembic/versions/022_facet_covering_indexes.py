"""Covering indexes for the filter-panel facet counts and group browsing.

``/search/facets`` aggregates over every tag, colour and image on each gallery
load. With these indexes SQLite answers the tag, colour and grid aggregates
from the index alone instead of visiting each table row (at 56k images: tags
283 -> 59 ms, colours 940 -> 163 ms, grid 40 -> 3 ms). ``variant_groups.created_at``
is the default group-browse sort.

The existing ``ix_tags_category_value``, ``ix_colors_color_hex`` and
``ix_images_gridded`` are prefixes of the new indexes but are kept: they are
declared by the models.

Revision ID: 022
Revises: 021
"""

from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None

_INDEXES = (
    ("ix_tags_category_value_image", "tags", ["category", "value", "image_id"]),
    ("ix_colors_color_hex_image", "colors", ["color_hex", "image_id"]),
    ("ix_images_gridded_grid_type", "images", ["gridded", "grid_type"]),
    ("ix_variant_groups_created_at", "variant_groups", ["created_at"]),
)


def upgrade() -> None:
    for name, table, columns in _INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _ in _INDEXES:
        op.drop_index(name, table_name=table)
