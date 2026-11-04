"""A stable identity for each gallery group (design/export-backup-move.md §2).

``variant_groups.uid`` is a random UUID (32 hex characters). Exports carry it and import
keeps it, so a group stays the same group across downloads and libraries; ids can't do
that, because SQLite reuses them and another library has its own.

A plain ``ADD COLUMN`` (nullable: SQLite can't add a NOT NULL column without a constant
default) plus a backfill and a unique index, so the triggers on the table are untouched.
The model always sets it.

Revision ID: 030
Revises: 029
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "030"
down_revision = "029"


def upgrade():
    op.add_column("variant_groups", sa.Column("uid", sa.String(32), nullable=True))
    bind = op.get_bind()
    ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM variant_groups"))]
    if ids:
        bind.execute(
            sa.text("UPDATE variant_groups SET uid = :uid WHERE id = :id"),
            [{"id": gid, "uid": uuid.uuid4().hex} for gid in ids],
        )
    op.create_index("ix_variant_groups_uid", "variant_groups", ["uid"], unique=True)


def downgrade():
    op.drop_index("ix_variant_groups_uid", table_name="variant_groups")
    op.drop_column("variant_groups", "uid")
