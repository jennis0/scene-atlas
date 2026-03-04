"""Add image_count column to variant_groups, database triggers to maintain it,
and missing indexes for search performance.

Revision ID: 014
Revises: 013
"""

import sqlalchemy as sa
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Fix 2: Stored image_count on variant_groups ---
    op.add_column(
        "variant_groups",
        sa.Column("image_count", sa.Integer(), nullable=False, server_default="0"),
    )

    # Backfill from current data
    op.execute(
        """
        UPDATE variant_groups
        SET image_count = (
            SELECT COUNT(*) FROM images WHERE images.variant_group_id = variant_groups.id
        )
        """
    )

    # Create triggers to auto-maintain image_count
    op.execute(
        """
        CREATE TRIGGER trg_images_group_count_insert
        AFTER INSERT ON images
        WHEN NEW.variant_group_id IS NOT NULL
        BEGIN
            UPDATE variant_groups
            SET image_count = image_count + 1
            WHERE id = NEW.variant_group_id;
        END
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_images_group_count_delete
        AFTER DELETE ON images
        WHEN OLD.variant_group_id IS NOT NULL
        BEGIN
            UPDATE variant_groups
            SET image_count = image_count - 1
            WHERE id = OLD.variant_group_id;
        END
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_images_group_count_update
        AFTER UPDATE OF variant_group_id ON images
        BEGIN
            UPDATE variant_groups
            SET image_count = image_count - 1
            WHERE id = OLD.variant_group_id
              AND OLD.variant_group_id IS NOT NULL;
            UPDATE variant_groups
            SET image_count = image_count + 1
            WHERE id = NEW.variant_group_id
              AND NEW.variant_group_id IS NOT NULL;
        END
        """
    )

    # --- Fix 5: Missing indexes for search performance ---

    # Relationship join columns (critical for eager loading)
    op.create_index("ix_tags_image_id", "tags", ["image_id"])
    op.create_index("ix_colors_image_id", "colors", ["image_id"])
    op.create_index("ix_images_variant_group_id", "images", ["variant_group_id"])

    # Filter columns used in search endpoint
    op.create_index("ix_images_gridded", "images", ["gridded"])
    op.create_index("ix_images_grid_type", "images", ["grid_type"])
    op.create_index("ix_images_image_type", "images", ["image_type"])
    op.create_index("ix_images_media_type", "images", ["media_type"])


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_images_media_type", "images")
    op.drop_index("ix_images_image_type", "images")
    op.drop_index("ix_images_grid_type", "images")
    op.drop_index("ix_images_gridded", "images")
    op.drop_index("ix_images_variant_group_id", "images")
    op.drop_index("ix_colors_image_id", "colors")
    op.drop_index("ix_tags_image_id", "tags")

    # Drop triggers
    op.execute("DROP TRIGGER IF EXISTS trg_images_group_count_update")
    op.execute("DROP TRIGGER IF EXISTS trg_images_group_count_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_images_group_count_insert")

    # Drop column
    op.drop_column("variant_groups", "image_count")
