"""Improve FTS5 tokenizer: add diacritics normalization (remove_diacritics 2).

FTS5 virtual tables cannot be ALTERed, so this migration drops and recreates
image_fts with the improved tokenizer, then rebuilds the index from the
content table.  The triggers are unchanged (they don't reference the tokenizer).

Revision ID: 015
Revises: 014
"""

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop existing FTS5 table (triggers fire on the content table, not this one)
    op.execute("DROP TABLE IF EXISTS image_fts")

    # Recreate with improved tokenizer: Porter stemmer + diacritics normalisation
    op.execute(
        """
        CREATE VIRTUAL TABLE image_fts USING fts5(
            name, filename, author, search_text,
            content='images', content_rowid='id',
            tokenize='porter unicode61 remove_diacritics 2'
        )
        """
    )

    # Rebuild the index from the content table
    op.execute("INSERT INTO image_fts(image_fts) VALUES ('rebuild')")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS image_fts")

    op.execute(
        """
        CREATE VIRTUAL TABLE image_fts USING fts5(
            name, filename, author, search_text,
            content='images', content_rowid='id',
            tokenize='porter unicode61'
        )
        """
    )

    op.execute("INSERT INTO image_fts(image_fts) VALUES ('rebuild')")
