"""FTS5 full-text search helpers."""

import logging
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.services.battlemap_parser import build_search_text

logger = logging.getLogger(__name__)


def _sanitize_fts_query(raw: str) -> str:
    """Strip FTS5 special syntax so user input always produces a valid MATCH query.

    FTS5 special chars: " ( ) ^ * - AND OR NOT (boolean operators are case-sensitive).
    Unbalanced quotes or dangling operators cause silent empty results; stripping
    them means "mine (underground)" correctly matches 'mine' and 'underground'
    instead of returning nothing.
    """
    # Remove FTS5 boolean operators (must be uppercase to be operators in FTS5)
    cleaned = re.sub(r"\b(AND|OR|NOT)\b", " ", raw)
    # Remove all chars that are special in FTS5 MATCH syntax
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    # Collapse whitespace and strip
    return " ".join(cleaned.split())


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

    User input is sanitized before passing to MATCH so that special characters
    (parentheses, quotes, AND/OR/NOT) never cause silent empty results.
    """
    fts_query = _sanitize_fts_query(query.strip())
    if not fts_query:
        return []

    rows = db.execute(
        text("""
        SELECT rowid, bm25(image_fts) AS score
        FROM image_fts
        WHERE image_fts MATCH :query
        ORDER BY score
        LIMIT :limit
    """),
        {"query": fts_query, "limit": limit},
    ).fetchall()

    return [(int(row[0]), float(row[1])) for row in rows]


def backfill_search_text(db: Session) -> int:
    """Populate search_text column for all images that don't have it yet.

    Reads name, filename, author, sub_variant, and tag values for each image,
    builds the CamelCase-split search text, and updates the column.
    Returns the number of rows updated.
    """
    # LEFT JOIN to get images + their tags in one query
    rows = db.execute(
        text("""
        SELECT i.id, i.name, i.filename, i.author, i.sub_variant,
               t.category, t.value
        FROM images i
        LEFT JOIN tags t ON t.image_id = i.id
        WHERE i.search_text IS NULL OR i.search_text = ''
        ORDER BY i.id
    """)
    ).fetchall()

    if not rows:
        return 0

    # Group tags by image ID
    images: dict[int, dict] = {}
    for row in rows:
        img_id = row[0]
        if img_id not in images:
            images[img_id] = {
                "name": row[1],
                "filename": row[2],
                "author": row[3],
                "sub_variant": row[4],
                "tags": [],
            }
        if row[5] is not None:  # tag category
            images[img_id]["tags"].append({"category": row[5], "value": row[6]})

    # Temporarily drop FTS triggers to avoid "malformed" errors during bulk UPDATE.
    # The FTS index will be rebuilt from scratch at the end.
    db.execute(text("DROP TRIGGER IF EXISTS image_fts_ai"))
    db.execute(text("DROP TRIGGER IF EXISTS image_fts_ad"))
    db.execute(text("DROP TRIGGER IF EXISTS image_fts_au"))

    for img_id, data in images.items():
        st = build_search_text(
            name=data["name"],
            filename=data["filename"],
            author=data["author"],
            tags=data["tags"],
            sub_variant=data["sub_variant"],
        )
        db.execute(
            text("UPDATE images SET search_text = :st WHERE id = :id"),
            {"st": st, "id": img_id},
        )

    db.commit()
    logger.info(f"Backfilled search_text for {len(images)} images")

    # Recreate triggers and rebuild FTS index
    db.execute(
        text("""
        CREATE TRIGGER image_fts_ai AFTER INSERT ON images BEGIN
            INSERT INTO image_fts(rowid, name, filename, author, search_text)
            VALUES (new.id, new.name, new.filename, new.author, new.search_text);
        END
    """)
    )
    db.execute(
        text("""
        CREATE TRIGGER image_fts_ad AFTER DELETE ON images BEGIN
            INSERT INTO image_fts(image_fts, rowid, name, filename, author, search_text)
            VALUES ('delete', old.id, old.name, old.filename, old.author, old.search_text);
        END
    """)
    )
    db.execute(
        text("""
        CREATE TRIGGER image_fts_au AFTER UPDATE ON images BEGIN
            INSERT INTO image_fts(image_fts, rowid, name, filename, author, search_text)
            VALUES ('delete', old.id, old.name, old.filename, old.author, old.search_text);
            INSERT INTO image_fts(rowid, name, filename, author, search_text)
            VALUES (new.id, new.name, new.filename, new.author, new.search_text);
        END
    """)
    )
    db.commit()

    fts_rebuild(db)
    return len(images)
