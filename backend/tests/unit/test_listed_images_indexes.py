"""Queries over listed images (``models.listed_images``) stay on covering indexes: the
partial indexes of migration 029 match the predicate exactly (ADR-028)."""

from __future__ import annotations

from sqlalchemy import event, func, select

from backend.app.models import Image, listed_images
from backend.app.services import search_service
from backend.app.services.search_service import SearchFilters


def _plans(db, run) -> list[str]:
    statements: list[tuple[str, object]] = []

    def grab(conn, cursor, statement, params, context, executemany):
        statements.append((statement, params))

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", grab)
    try:
        run()
    finally:
        event.remove(engine, "before_cursor_execute", grab)
    plans = []
    for statement, params in statements:
        rows = db.connection().exec_driver_sql("EXPLAIN QUERY PLAN " + statement, params).all()
        plans.append(" | ".join(row[-1] for row in rows))
    return plans


def test_the_predicate_renders_as_the_partial_indexes_condition(db_session):
    sql = str(select(Image.id).where(listed_images()).compile(db_session.get_bind()))
    assert "images.awaiting_grouping = 0" in sql


def test_facets_and_browsing_use_the_partial_covering_indexes(db_session):
    plans = _plans(db_session, lambda: search_service.get_facets(db_session))
    plans += _plans(
        db_session,
        lambda: search_service.browse_images(
            db_session, SearchFilters(), "created_at", "desc", 50, 0
        ),
    )
    plans += _plans(
        db_session,
        lambda: db_session.scalar(select(func.count(Image.id)).where(listed_images())),
    )
    joined = "\n".join(plans)
    for index in (
        "ix_images_listed_author",
        "ix_images_listed_grid",
        "ix_images_listed_type",
        "ix_images_listed_media",
        "ix_images_listed_created",
        "ix_images_listed_id",
    ):
        assert f"COVERING INDEX {index}" in joined or f"INDEX {index}" in joined, index
    for plan in plans:
        # The images table is never scanned row by row for these
        assert "SCAN images |" not in plan + " |", plan
