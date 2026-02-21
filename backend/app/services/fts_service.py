"""FTS5 full-text search helpers."""

from sqlalchemy import text
from sqlalchemy.orm import Session


def fts_rebuild(db: Session) -> None:
    """Rebuild the entire FTS5 index from the images table.

    Should be called after bulk imports to ensure the index is in sync.
    Individual row changes are handled by SQLite triggers.
    """
    db.execute(text("INSERT INTO image_fts(image_fts) VALUES ('rebuild')"))
    db.commit()


def fts_search(db: Session, query: str, limit: int = 500) -> list[tuple[int, float]]:
    """Search images via FTS5 BM25 ranking.

    Returns list of (image_id, bm25_score) pairs sorted by relevance.
    BM25 scores from FTS5 are negative (more negative = better match).
    Porter stemmer is active, so 'forests' matches 'forest', 'mining' matches 'mine'.
    """
    fts_query = query.strip()
    if not fts_query:
        return []

    try:
        rows = db.execute(text("""
            SELECT rowid, bm25(image_fts) AS score
            FROM image_fts
            WHERE image_fts MATCH :query
            ORDER BY score
            LIMIT :limit
        """), {"query": fts_query, "limit": limit}).fetchall()

        return [(int(row[0]), float(row[1])) for row in rows]
    except Exception:
        # FTS5 MATCH syntax can raise if the query contains special chars.
        # Fall back gracefully to an empty result.
        return []
