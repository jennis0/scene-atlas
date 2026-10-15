"""Remove the legacy import pipeline's schema (ADR-018).

Drops import_group_jobs and the old import_jobs columns. Old-flow job rows
(statuses that no longer exist) are deleted; their images are kept, with
import_job_id cleared. Scene Atlas is unreleased, so no data is migrated.

Revision ID: 021
Revises: 020
"""

import sqlalchemy as sa
from alembic import op

revision = "021"
down_revision = "020"

_NEW_STATUSES = ("active", "paused", "completed", "cancelled")
_LEGACY_COLUMNS = (
    "total_files",
    "error_message",
    "analysis_result",
    "job_warnings",
    "total_file_size",
)


def upgrade():
    conn = op.get_bind()
    legacy = [
        row[0]
        for row in conn.execute(
            sa.text("SELECT id FROM import_jobs WHERE status NOT IN :statuses").bindparams(
                sa.bindparam("statuses", expanding=True)
            ),
            {"statuses": list(_NEW_STATUSES)},
        )
    ]
    for job_id in legacy:
        conn.execute(
            sa.text("UPDATE images SET import_job_id = NULL WHERE import_job_id = :id"),
            {"id": job_id},
        )
        conn.execute(sa.text("DELETE FROM import_jobs WHERE id = :id"), {"id": job_id})

    op.drop_table("import_group_jobs")
    with op.batch_alter_table("import_jobs") as batch:
        for column in _LEGACY_COLUMNS:
            batch.drop_column(column)


def downgrade():
    with op.batch_alter_table("import_jobs") as batch:
        batch.add_column(sa.Column("total_files", sa.Integer(), server_default="0"))
        batch.add_column(sa.Column("error_message", sa.Text(), nullable=True))
        batch.add_column(sa.Column("analysis_result", sa.Text(), nullable=True))
        batch.add_column(sa.Column("job_warnings", sa.Text(), nullable=True))
        batch.add_column(sa.Column("total_file_size", sa.Integer(), server_default="0"))
    op.create_table(
        "import_group_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("import_jobs.id"), nullable=False),
        sa.Column("variant_group_name", sa.String(), nullable=False),
        sa.Column("author", sa.String(), nullable=True),
        sa.Column("total_files", sa.Integer(), server_default="0"),
        sa.Column("processed_files", sa.Integer(), server_default="0"),
        sa.Column("failed_files", sa.Integer(), server_default="0"),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("file_errors", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_group_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_import_group_jobs_job_id", "import_group_jobs", ["job_id"])
