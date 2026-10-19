"""The linked library (design/library-setup.md §4.1).

Adds ``library_sources`` (the linked folder) and ``source_files`` (the durable index of
its files), lets an image's original be a linked file instead of a stored one
(``images.storage_key`` nullable, ``images.source_file_id``, and a CHECK that one of them
is set), and links import items and jobs to what they read (``import_items.source_file_id``,
``import_jobs.library_source_id``).

Making ``storage_key`` nullable rebuilds the images table, which drops its triggers in
SQLite, so the full-text and group-count triggers are created again.

Revision ID: 028
Revises: 027
"""

import sqlalchemy as sa
from alembic import op

revision = "028"
down_revision = "027"

# The triggers on images, as migrations 001 and 014 created them.
_IMAGE_TRIGGERS = (
    """
    CREATE TRIGGER image_fts_ai AFTER INSERT ON images BEGIN
        INSERT INTO image_fts(rowid, name, filename, author, search_text)
        VALUES (new.id, new.name, new.filename, new.author, new.search_text);
    END
    """,
    """
    CREATE TRIGGER image_fts_ad AFTER DELETE ON images BEGIN
        INSERT INTO image_fts(image_fts, rowid, name, filename, author, search_text)
        VALUES ('delete', old.id, old.name, old.filename, old.author, old.search_text);
    END
    """,
    """
    CREATE TRIGGER image_fts_au AFTER UPDATE ON images BEGIN
        INSERT INTO image_fts(image_fts, rowid, name, filename, author, search_text)
        VALUES ('delete', old.id, old.name, old.filename, old.author, old.search_text);
        INSERT INTO image_fts(rowid, name, filename, author, search_text)
        VALUES (new.id, new.name, new.filename, new.author, new.search_text);
    END
    """,
    """
    CREATE TRIGGER trg_images_group_count_insert
    AFTER INSERT ON images
    WHEN NEW.variant_group_id IS NOT NULL
    BEGIN
        UPDATE variant_groups
        SET image_count = image_count + 1
        WHERE id = NEW.variant_group_id;
    END
    """,
    """
    CREATE TRIGGER trg_images_group_count_delete
    AFTER DELETE ON images
    WHEN OLD.variant_group_id IS NOT NULL
    BEGIN
        UPDATE variant_groups
        SET image_count = image_count - 1
        WHERE id = OLD.variant_group_id;
    END
    """,
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
    """,
)
_TRIGGER_NAMES = (
    "image_fts_ai",
    "image_fts_ad",
    "image_fts_au",
    "trg_images_group_count_insert",
    "trg_images_group_count_delete",
    "trg_images_group_count_update",
)


def _recreate_image_triggers() -> None:
    for name in _TRIGGER_NAMES:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    for trigger in _IMAGE_TRIGGERS:
        op.execute(trigger)


def upgrade():
    op.create_table(
        "library_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("last_scan_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "source_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("rel_key", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("mtime_ns", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("missing_since", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["library_sources.id"]),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "rel_key", name="uq_source_files_source_key"),
    )
    op.create_index("ix_source_files_source_state", "source_files", ["source_id", "state"])
    op.create_index("ix_source_files_image", "source_files", ["image_id"])

    with op.batch_alter_table("images") as batch:
        batch.alter_column("storage_key", existing_type=sa.String(), nullable=True)
        batch.add_column(sa.Column("source_file_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_images_source_file", "source_files", ["source_file_id"], ["id"]
        )
        batch.create_check_constraint(
            "ck_images_original", "storage_key IS NOT NULL OR source_file_id IS NOT NULL"
        )
    _recreate_image_triggers()
    op.create_index("ix_images_source_file_id", "images", ["source_file_id"], unique=True)

    with op.batch_alter_table("import_items") as batch:
        batch.add_column(sa.Column("source_file_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_import_items_source_file", "source_files", ["source_file_id"], ["id"]
        )
    op.create_index("ix_import_items_source_file", "import_items", ["source_file_id"])

    with op.batch_alter_table("import_jobs") as batch:
        batch.add_column(sa.Column("library_source_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_import_jobs_library_source", "library_sources", ["library_source_id"], ["id"]
        )


def downgrade():
    # Linked images have no stored original, so they can't survive the NOT NULL.
    op.execute(
        "DELETE FROM tags WHERE image_id IN (SELECT id FROM images WHERE storage_key IS NULL)"
    )
    op.execute(
        "DELETE FROM colors WHERE image_id IN (SELECT id FROM images WHERE storage_key IS NULL)"
    )
    op.execute("DELETE FROM images WHERE storage_key IS NULL")

    with op.batch_alter_table("import_jobs") as batch:
        batch.drop_constraint("fk_import_jobs_library_source", type_="foreignkey")
        batch.drop_column("library_source_id")
    op.drop_index("ix_import_items_source_file", table_name="import_items")
    with op.batch_alter_table("import_items") as batch:
        batch.drop_constraint("fk_import_items_source_file", type_="foreignkey")
        batch.drop_column("source_file_id")
    op.drop_index("ix_images_source_file_id", table_name="images")
    with op.batch_alter_table("images") as batch:
        batch.drop_constraint("ck_images_original", type_="check")
        batch.drop_constraint("fk_images_source_file", type_="foreignkey")
        batch.drop_column("source_file_id")
        batch.alter_column("storage_key", existing_type=sa.String(), nullable=False)
    _recreate_image_triggers()

    op.drop_index("ix_source_files_image", table_name="source_files")
    op.drop_index("ix_source_files_source_state", table_name="source_files")
    op.drop_table("source_files")
    op.drop_table("library_sources")
