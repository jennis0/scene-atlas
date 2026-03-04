"""Add composite index on tags(category, value) for faster tag filtering.

The search endpoint filters tags with (category, value) pairs in an OR clause.
A composite index avoids the full-table-scan that single-column indexes produce
when both columns are constrained.

Revision ID: 016
Revises: 015
"""

from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_tags_category_value", "tags", ["category", "value"])


def downgrade() -> None:
    op.drop_index("ix_tags_category_value", table_name="tags")
