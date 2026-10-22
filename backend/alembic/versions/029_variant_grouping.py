"""Variant grouping v2 (ADR-028, design/variant-grouping.md).

Adds ``image_grouping_features`` (per-image content features: a 256-bit pHash and a
32×32 edge map, written by the ingest worker), ``variant_groups.edited_at`` (set by user
group edits; automatic grouping leaves edited groups alone),
``import_jobs.grouping_refined_at`` (when content-aware grouping last refined the whole job),
and on ``import_groups`` the group's ``partition_key`` (its effective top-level folder, for
imports refined partition by partition) and ``grouping_refined_at`` (when its partition was
refined; a group is reviewable only then), and ``import_jobs.grouping_refinable``.

**Existing imports keep their groups** (ADR-028). Every job sealed before this (``planned_at``
set, finished or not) was grouped by the old parser, and its groups may have been curated
before edits were recorded (``edited_at`` stays NULL for them). Such jobs are marked
``grouping_refinable = 0`` and stamped refined, with their import groups: refinement never
runs on them (a later re-open only stamps them again, without a walk), and their groups stay
reviewable as before. Unsealed jobs will be sealed by the tree walk and stay refinable.

The columns are plain ``ADD COLUMN``s, not table rebuilds, so the triggers on images
(full-text index, group image counts) are untouched. Images imported before this have
no features row.

Revision ID: 029
Revises: 028
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

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
    op.add_column("variant_groups", sa.Column("edited_at", sa.DateTime(), nullable=True))
    op.add_column("import_jobs", sa.Column("grouping_refined_at", sa.DateTime(), nullable=True))
    op.add_column("import_groups", sa.Column("partition_key", sa.String(), nullable=True))
    op.add_column("import_groups", sa.Column("grouping_refined_at", sa.DateTime(), nullable=True))
    op.add_column(
        "import_jobs",
        sa.Column("grouping_refinable", sa.Boolean(), nullable=False, server_default="1"),
    )
    _keep_existing_groups()


def _keep_existing_groups() -> None:
    """Jobs sealed by the old parser are never refined, and their groups stay reviewable."""
    now = datetime.now(UTC).replace(tzinfo=None)
    op.get_bind().execute(
        sa.text(
            "UPDATE import_jobs SET grouping_refinable = 0, "
            "grouping_refined_at = COALESCE(completed_at, :now) "
            "WHERE planned_at IS NOT NULL"
        ).bindparams(sa.bindparam("now", now, type_=sa.DateTime()))
    )
    op.get_bind().execute(
        sa.text(
            "UPDATE import_groups SET grouping_refined_at = ("
            "SELECT import_jobs.grouping_refined_at FROM import_jobs "
            "WHERE import_jobs.id = import_groups.job_id) "
            "WHERE job_id IN (SELECT id FROM import_jobs WHERE grouping_refinable = 0)"
        )
    )


def downgrade():
    # SQLite's native DROP COLUMN (3.35+), as migrations 014 and 018 use: no rebuild
    op.drop_column("import_jobs", "grouping_refinable")
    op.drop_column("import_groups", "grouping_refined_at")
    op.drop_column("import_groups", "partition_key")
    op.drop_column("import_jobs", "grouping_refined_at")
    op.drop_column("variant_groups", "edited_at")
    op.drop_table("image_grouping_features")
