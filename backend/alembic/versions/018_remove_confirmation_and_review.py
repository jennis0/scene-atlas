"""Remove import confirmation columns and needs_review.

Revision ID: 018
Revises: 017
"""

from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"


def upgrade():
    conn = op.get_bind()

    # Backfill awaiting_input jobs based on child group states
    awaiting_jobs = conn.execute(
        sa.text("SELECT id FROM import_jobs WHERE status = 'awaiting_input'")
    ).fetchall()

    for (job_id,) in awaiting_jobs:
        has_failure = conn.execute(
            sa.text(
                "SELECT 1 FROM import_group_jobs "
                "WHERE job_id = :jid AND status = 'failed' LIMIT 1"
            ),
            {"jid": job_id},
        ).fetchone()
        new_status = "failed" if has_failure else "completed"
        conn.execute(
            sa.text(
                "UPDATE import_jobs SET status = :s, completed_at = CURRENT_TIMESTAMP "
                "WHERE id = :jid"
            ),
            {"s": new_status, "jid": job_id},
        )

    # Clear needs_review on all images (they're all "in" now)
    conn.execute(sa.text("UPDATE images SET needs_review = 0 WHERE needs_review = 1"))

    op.drop_column("import_jobs", "pending_groups")
    op.drop_column("import_jobs", "all_confirmed")
    op.drop_index("ix_images_needs_review", table_name="images")
    op.drop_column("images", "needs_review")


def downgrade():
    op.add_column(
        "import_jobs",
        sa.Column("all_confirmed", sa.Boolean(), server_default="0", nullable=False),
    )
    op.add_column(
        "import_jobs",
        sa.Column("pending_groups", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "images",
        sa.Column("needs_review", sa.Boolean(), nullable=True),
    )
    op.create_index("ix_images_needs_review", "images", ["needs_review"])
