"""Per-item ingest model (ADR-018).

Adds import_groups and import_items, the per-item ingest columns on import_jobs,
and the stored/pixel/perceptual hash columns on images.

The legacy import_group_jobs table and old import_jobs columns are removed in a
later migration once the old pipeline is deleted.

Revision ID: 020
Revises: 019
"""

import sqlalchemy as sa
from alembic import op

revision = "020"
down_revision = "019"


def upgrade():
    op.add_column(
        "import_jobs",
        sa.Column("default_image_type", sa.String(), nullable=False, server_default="battlemap"),
    )
    op.add_column("import_jobs", sa.Column("planned_at", sa.DateTime(), nullable=True))
    op.add_column("import_jobs", sa.Column("last_upload_at", sa.DateTime(), nullable=True))
    op.add_column("import_jobs", sa.Column("dismissed_at", sa.DateTime(), nullable=True))

    op.add_column("images", sa.Column("stored_hash", sa.String(64), nullable=True))
    op.add_column("images", sa.Column("pixel_hash", sa.String(64), nullable=True))
    op.add_column("images", sa.Column("phash", sa.Integer(), nullable=True))
    op.create_index("ix_images_stored_hash", "images", ["stored_hash"])
    op.create_index("ix_images_pixel_hash", "images", ["pixel_hash"])

    op.create_table(
        "import_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("import_jobs.id"), nullable=False),
        sa.Column("author", sa.String(), nullable=True),
        sa.Column("group_name", sa.String(), nullable=False),
        sa.Column(
            "image_group_id", sa.Integer(), sa.ForeignKey("variant_groups.id"), nullable=True
        ),
        sa.Column("merged_into_existing", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_import_groups_job_id", "import_groups", ["job_id"])

    op.create_table(
        "import_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("import_jobs.id"), nullable=False),
        sa.Column(
            "import_group_id", sa.Integer(), sa.ForeignKey("import_groups.id"), nullable=True
        ),
        sa.Column("kind", sa.String(), nullable=False, server_default="image"),
        sa.Column("relative_path", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("last_modified", sa.Integer(), nullable=True),
        sa.Column("image_type", sa.String(), nullable=False, server_default="battlemap"),
        sa.Column("parsed", sa.Text(), nullable=True),
        sa.Column("state", sa.String(), nullable=False, server_default="awaiting_bytes"),
        sa.Column("staging_key", sa.String(), nullable=True),
        sa.Column("source_hash", sa.String(64), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_after", sa.DateTime(), nullable=True),
        sa.Column("error_kind", sa.String(), nullable=True),
        sa.Column("error_stage", sa.String(), nullable=True),
        sa.Column("error_reason", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("image_id", sa.Integer(), sa.ForeignKey("images.id"), nullable=True),
        sa.Column("duplicate_of_image_id", sa.Integer(), sa.ForeignKey("images.id"), nullable=True),
        sa.Column("duplicate_tier", sa.String(), nullable=True),
        sa.Column("allow_duplicate", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("similar_to_image_id", sa.Integer(), sa.ForeignKey("images.id"), nullable=True),
        sa.Column("similarity_distance", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("job_id", "relative_path", name="uq_import_items_job_path"),
    )
    op.create_index("ix_import_items_state_job", "import_items", ["state", "job_id"])
    op.create_index("ix_import_items_job_state", "import_items", ["job_id", "state"])
    op.create_index("ix_import_items_job_group", "import_items", ["job_id", "import_group_id"])


def downgrade():
    op.drop_index("ix_import_items_job_group", table_name="import_items")
    op.drop_index("ix_import_items_job_state", table_name="import_items")
    op.drop_index("ix_import_items_state_job", table_name="import_items")
    op.drop_table("import_items")
    op.drop_index("ix_import_groups_job_id", table_name="import_groups")
    op.drop_table("import_groups")
    op.drop_index("ix_images_pixel_hash", table_name="images")
    op.drop_index("ix_images_stored_hash", table_name="images")
    op.drop_column("images", "phash")
    op.drop_column("images", "pixel_hash")
    op.drop_column("images", "stored_hash")
    op.drop_column("import_jobs", "dismissed_at")
    op.drop_column("import_jobs", "last_upload_at")
    op.drop_column("import_jobs", "planned_at")
    op.drop_column("import_jobs", "default_image_type")
