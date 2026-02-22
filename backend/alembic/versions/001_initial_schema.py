"""Initial schema — full database schema as of project start.

This migration creates the complete initial schema:
- All ORM tables (images, variant_groups, tags, tag_categories, colors,
  import_jobs, import_group_jobs)
- All indexes
- FTS5 virtual table (image_fts) and its three sync triggers

For databases that predate Alembic, init_db() detects the existing tables
and stamps at this revision without running the migration, since those
databases are already in the target state.

Revision ID: 001
Revises: (none)
Create Date: 2026-02-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # variant_groups — created first because images has a FK to it
    # -----------------------------------------------------------------------
    op.create_table(
        "variant_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("base_name", sa.String(), nullable=False),
        sa.Column("author", sa.String(), nullable=True),
        sa.Column("primary_image_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_variant_groups_id", "variant_groups", ["id"])
    op.create_index("ix_variant_groups_base_name", "variant_groups", ["base_name"])
    op.create_index("ix_variant_groups_author", "variant_groups", ["author"])

    # -----------------------------------------------------------------------
    # images
    # -----------------------------------------------------------------------
    op.create_table(
        "images",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("author", sa.String(), nullable=True),
        sa.Column("variant_group_id", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("gridded", sa.Boolean(), nullable=True),
        sa.Column("grid_width", sa.Integer(), nullable=True),
        sa.Column("grid_height", sa.Integer(), nullable=True),
        sa.Column("sub_variant", sa.String(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("search_text", sa.Text(), nullable=True),
        sa.Column("thumbnail_key", sa.String(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["variant_group_id"], ["variant_groups.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_images_id", "images", ["id"])
    op.create_index("ix_images_filename", "images", ["filename"])
    op.create_index("ix_images_storage_key", "images", ["storage_key"])
    op.create_index("ix_images_name", "images", ["name"])
    op.create_index("ix_images_author", "images", ["author"])
    op.create_index("ix_images_needs_review", "images", ["needs_review"])
    op.create_index("ix_images_content_hash", "images", ["content_hash"])

    # variant_groups.primary_image_id → images (deferred FK to break the circle)
    with op.batch_alter_table("variant_groups") as batch_op:
        batch_op.create_foreign_key(
            "fk_variant_groups_primary_image",
            "images",
            ["primary_image_id"],
            ["id"],
        )

    # -----------------------------------------------------------------------
    # tag_categories
    # -----------------------------------------------------------------------
    op.create_table(
        "tag_categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("common_values", sa.Text(), nullable=True),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_tag_categories_id", "tag_categories", ["id"])
    op.create_index("ix_tag_categories_name", "tag_categories", ["name"])

    # -----------------------------------------------------------------------
    # tags
    # -----------------------------------------------------------------------
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tags_id", "tags", ["id"])
    op.create_index("ix_tags_category", "tags", ["category"])
    op.create_index("ix_tags_value", "tags", ["value"])

    # -----------------------------------------------------------------------
    # colors
    # -----------------------------------------------------------------------
    op.create_table(
        "colors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("color_hex", sa.String(7), nullable=False),
        sa.Column("percentage", sa.Float(), nullable=True),
        sa.Column("color_order", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_colors_id", "colors", ["id"])
    op.create_index("ix_colors_color_hex", "colors", ["color_hex"])

    # -----------------------------------------------------------------------
    # import_jobs
    # -----------------------------------------------------------------------
    op.create_table(
        "import_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("source_label", sa.String(), nullable=True),
        sa.Column("total_files", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # -----------------------------------------------------------------------
    # import_group_jobs
    # -----------------------------------------------------------------------
    op.create_table(
        "import_group_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("variant_group_name", sa.String(), nullable=False),
        sa.Column("author", sa.String(), nullable=True),
        sa.Column("total_files", sa.Integer(), nullable=True),
        sa.Column("processed_files", sa.Integer(), nullable=True),
        sa.Column("failed_files", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("flow_run_id", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["import_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_group_jobs_job_id", "import_group_jobs", ["job_id"])

    # -----------------------------------------------------------------------
    # FTS5 virtual table and sync triggers
    # Must use raw SQL — SQLAlchemy/Alembic have no FTS5 support.
    # -----------------------------------------------------------------------
    op.execute("""
        CREATE VIRTUAL TABLE image_fts USING fts5(
            name, filename, author, search_text,
            content='images', content_rowid='id',
            tokenize='porter unicode61'
        )
    """)

    op.execute("""
        CREATE TRIGGER image_fts_ai AFTER INSERT ON images BEGIN
            INSERT INTO image_fts(rowid, name, filename, author, search_text)
            VALUES (new.id, new.name, new.filename, new.author, new.search_text);
        END
    """)
    op.execute("""
        CREATE TRIGGER image_fts_ad AFTER DELETE ON images BEGIN
            INSERT INTO image_fts(image_fts, rowid, name, filename, author, search_text)
            VALUES ('delete', old.id, old.name, old.filename, old.author, old.search_text);
        END
    """)
    op.execute("""
        CREATE TRIGGER image_fts_au AFTER UPDATE ON images BEGIN
            INSERT INTO image_fts(image_fts, rowid, name, filename, author, search_text)
            VALUES ('delete', old.id, old.name, old.filename, old.author, old.search_text);
            INSERT INTO image_fts(rowid, name, filename, author, search_text)
            VALUES (new.id, new.name, new.filename, new.author, new.search_text);
        END
    """)


def downgrade() -> None:
    # Drop triggers first (they reference image_fts and images)
    op.execute("DROP TRIGGER IF EXISTS image_fts_au")
    op.execute("DROP TRIGGER IF EXISTS image_fts_ad")
    op.execute("DROP TRIGGER IF EXISTS image_fts_ai")
    op.execute("DROP TABLE IF EXISTS image_fts")

    op.drop_table("import_group_jobs")
    op.drop_table("import_jobs")
    op.drop_table("colors")
    op.drop_table("tags")
    op.drop_table("tag_categories")

    # Remove the deferred FK before dropping images
    with op.batch_alter_table("variant_groups") as batch_op:
        batch_op.drop_constraint("fk_variant_groups_primary_image", type_="foreignkey")

    op.drop_table("images")
    op.drop_table("variant_groups")
