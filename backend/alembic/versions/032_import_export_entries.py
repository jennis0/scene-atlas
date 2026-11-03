"""Scene Atlas metadata that came with an import (design/export-backup-move.md §6).

- ``import_export_entries``: one row per image entry of the ``scene-atlas.jsonl`` files an
  import carried, keyed by the job and the hash of the file it describes, so the worker
  matches each file it decodes to its entry. ``source`` names the metadata file it came
  from; ``encoder`` is the vision encoder its vector is from.
- ``import_jobs.export_model``: the first metadata file's header model (JSON); set when a
  job has metadata at all.
- ``import_jobs.export_note``: why a job's metadata wasn't used, for its report.
- ``import_jobs.metadata_pending``: its metadata files still to load (JSON); the worker
  holds its items until they are.

Revision ID: 032
Revises: 031
"""

import sqlalchemy as sa
from alembic import op

revision = "032"
down_revision = "031"


def upgrade():
    op.create_table(
        "import_export_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("import_jobs.id"), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("stored_hash", sa.String(64), nullable=False),
        sa.Column("encoder", sa.String(64), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("image", sa.Text(), nullable=False),
        sa.Column("group_entry", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_import_export_entries_job_hash", "import_export_entries", ["job_id", "stored_hash"]
    )
    op.add_column("import_jobs", sa.Column("export_model", sa.Text(), nullable=True))
    op.add_column("import_jobs", sa.Column("export_note", sa.Text(), nullable=True))
    op.add_column("import_jobs", sa.Column("metadata_pending", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("import_jobs", "metadata_pending")
    op.drop_column("import_jobs", "export_note")
    op.drop_column("import_jobs", "export_model")
    op.drop_index("ix_import_export_entries_job_hash", table_name="import_export_entries")
    op.drop_table("import_export_entries")
