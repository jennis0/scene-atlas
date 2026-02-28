"""Add pending_groups column to import_jobs for explicit state machine.

Replaces the fragile derived-from-analysis_result pending count with an
explicit counter that the frontend syncs on each confirm call.

Revision ID: 011
Revises: 010
Create Date: 2026-02-28
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "import_jobs",
        sa.Column("pending_groups", sa.Integer(), server_default="0", nullable=False),
    )

    # Backfill pending_groups for non-terminal jobs that have analysis data.
    # This handles the edge case of a job in staging/active when the migration runs.
    conn = op.get_bind()
    jobs = conn.execute(
        text(
            "SELECT id, analysis_result FROM import_jobs "
            "WHERE status NOT IN ('completed','failed','cancelled','expired') "
            "AND analysis_result IS NOT NULL"
        )
    ).fetchall()

    for job_id, analysis_json in jobs:
        try:
            parsed = json.loads(analysis_json)
            if isinstance(parsed, dict):
                count = len(parsed.get("summary", []))
            else:
                count = len(parsed)
            submitted = conn.execute(
                text("SELECT COUNT(*) FROM import_group_jobs WHERE job_id = :jid"),
                {"jid": job_id},
            ).scalar()
            pending = max(0, count - (submitted or 0))
            conn.execute(
                text("UPDATE import_jobs SET pending_groups = :pg WHERE id = :jid"),
                {"pg": pending, "jid": job_id},
            )
        except (json.JSONDecodeError, TypeError, KeyError):
            pass  # Leave at 0 for corrupted data


def downgrade() -> None:
    op.drop_column("import_jobs", "pending_groups")
