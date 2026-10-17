"""The ORM models must describe the schema that the Alembic migrations build.

A new column, index or constraint has to be added to both. Known, accepted
differences are listed explicitly so anything new fails the test.
"""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from backend.app.models.database import Base

ACCEPTED = {
    # FTS5 virtual table and its shadow tables are created by raw SQL, not the models.
    ("remove_table", "image_fts"),
    ("remove_table", "image_fts_config"),
    ("remove_table", "image_fts_content"),
    ("remove_table", "image_fts_data"),
    ("remove_table", "image_fts_docsize"),
    ("remove_table", "image_fts_idx"),
    # SQLite can't add a foreign key without a table rebuild; enforced by the model only.
    ("add_fk", "images"),
    # Migration 001 created a plain index plus a UNIQUE constraint; the model declares a unique index.
    ("remove_index", "ix_tag_categories_name"),
    ("add_index", "ix_tag_categories_name"),
    ("modify_nullable", "app_settings.updated_at"),
}


def _key(diff) -> tuple[str, str]:
    if isinstance(diff, list):  # column-level changes come wrapped in a list
        op, _schema, table, column, *_ = diff[0]
        return op, f"{table}.{column}"
    op, obj = diff[0], diff[1]
    if op in ("add_fk", "remove_fk"):
        return op, obj.parent.name
    return op, obj.name


def test_models_match_migrations(tmp_db):
    engine, _ = tmp_db
    with engine.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    unexpected = [d for d in diffs if _key(d) not in ACCEPTED]
    assert not unexpected, f"Models and migrations disagree: {unexpected}"
