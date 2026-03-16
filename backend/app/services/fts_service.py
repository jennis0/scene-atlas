"""FTS5 full-text search helpers."""

import json
import logging
import re
import threading
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.services.image_parser import build_search_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level alias vocabulary cache (TTL-based, avoids per-request DB hit)
# ---------------------------------------------------------------------------

_alias_vocab: dict[str, str] | None = None  # alias_or_canonical -> canonical
_alias_reverse: dict[str, set[str]] | None = None  # canonical -> {aliases}
_alias_vocab_loaded_at: float = 0.0
_ALIAS_TTL = 300.0  # 5 minutes
_alias_lock = threading.Lock()


def _load_alias_vocab(db: Session) -> tuple[dict[str, str], dict[str, set[str]]]:
    """Load tag alias vocabulary from the DB into forward and reverse maps."""
    from ..models.database import TagCategory  # local import to avoid circularity

    vocab: dict[str, str] = {}
    reverse: dict[str, set[str]] = {}

    categories = db.query(TagCategory).all()
    for cat in categories:
        if not cat.common_values:
            continue
        try:
            values = (
                json.loads(cat.common_values)
                if isinstance(cat.common_values, str)
                else cat.common_values
            )
        except (json.JSONDecodeError, TypeError):
            logger.warning("Invalid common_values JSON for category '%s'", cat.name)
            continue

        from .image_parser import parse_tag_vocab_entries

        for alias, canonical in parse_tag_vocab_entries(values).items():
            vocab[alias] = canonical
            reverse.setdefault(canonical, set()).add(alias)

    return vocab, reverse


def get_alias_vocab(db: Session) -> tuple[dict[str, str], dict[str, set[str]]]:
    """Return cached alias vocab, refreshing if TTL expired."""
    global _alias_vocab, _alias_reverse, _alias_vocab_loaded_at

    with _alias_lock:
        now = time.monotonic()
        if _alias_vocab is not None and (now - _alias_vocab_loaded_at) < _ALIAS_TTL:
            return _alias_vocab, _alias_reverse  # type: ignore[return-value]

        _alias_vocab, _alias_reverse = _load_alias_vocab(db)
        _alias_vocab_loaded_at = now
        return _alias_vocab, _alias_reverse


def get_alias_expansions(query: str, db: Session) -> list[str]:
    """Return alias/canonical forms for query words that are not already in the query.

    Used to run a separate lower-weight FTS pass that expands synonym forms.
    Kept separate from the main query to avoid BM25 score dilution.

    Words inside quoted phrases are excluded from alias expansion — the user
    explicitly requested an exact phrase match for those terms.
    """
    vocab, reverse = get_alias_vocab(db)
    sanitized = _sanitize_fts_query(query)
    # Only expand loose (non-phrase) tokens.
    tokens = _parse_fts_tokens(sanitized)
    words = set()
    for token in tokens:
        if not token.startswith('"'):
            words.add(token.lower())
    extras: set[str] = set()

    for word in words:
        # word is an alias → add its canonical
        canonical = vocab.get(word)
        if canonical and canonical not in words:
            extras.add(canonical)
        # word is canonical → add its aliases
        for alias in reverse.get(word, set()):
            if alias not in words:
                extras.add(alias)

    return list(extras)


def invalidate_alias_cache() -> None:
    """Force reload of alias vocab on next use (call after tag category changes)."""
    global _alias_vocab_loaded_at
    with _alias_lock:
        _alias_vocab_loaded_at = 0.0


# ---------------------------------------------------------------------------
# FTS5 search
# ---------------------------------------------------------------------------


def _sanitize_fts_query(raw: str) -> str:
    """Sanitize user input into a valid FTS5 MATCH expression.

    Preserves double-quoted phrases for exact phrase matching (e.g. ``"forest
    shrine"`` matches only adjacent words).  Single-word phrases are degraded
    to plain terms.  Unbalanced quotes are treated as loose words.

    All other FTS5 special syntax (boolean operators, parentheses, carets,
    asterisks) is stripped so user input never causes silent empty results.
    """
    # Remove FTS5 boolean operators (must be uppercase to be operators in FTS5)
    cleaned = re.sub(r"\b(AND|OR|NOT)\b", " ", raw)

    # Extract balanced quoted phrase contents before stripping special chars.
    phrases: list[str] = re.findall(r'"([^"]*)"', cleaned)
    # Remove matched quoted regions so they don't appear in the loose portion.
    loose = re.sub(r'"[^"]*"', " ", cleaned)

    # Sanitize the loose portion (strip all non-word/non-space chars).
    loose = re.sub(r"[^\w\s]", " ", loose)
    loose_words = loose.split()

    # Sanitize each phrase interior and keep only multi-word phrases.
    phrase_tokens: list[str] = []
    for phrase in phrases:
        inner = re.sub(r"[^\w\s]", " ", phrase)
        words = inner.split()
        if len(words) >= 2:
            phrase_tokens.append(f'"{" ".join(words)}"')
        else:
            # Single-word or empty phrase degrades to a plain term.
            loose_words.extend(words)

    parts = phrase_tokens + loose_words
    return " ".join(parts)


def _parse_fts_tokens(fts_query: str) -> list[str]:
    """Split a sanitized FTS query into tokens (quoted phrases or single words).

    >>> _parse_fts_tokens('"forest shrine" cave')
    ['"forest shrine"', 'cave']
    """
    return re.findall(r'"[^"]*"|\S+', fts_query)


def _run_fts(db: Session, match_query: str, limit: int) -> list[tuple[int, float]]:
    """Execute a raw FTS5 MATCH query with BM25 column weights.

    Column weights (matching image_fts column order: name, filename, author, search_text):
    - name       × 10.0 — title matches are highest priority
    - filename   × 1.0  — useful fallback
    - author     × 0.5  — rarely matches intent
    - search_text × 5.0 — tag values are second priority
    """
    rows = db.execute(
        text("""
        SELECT rowid, bm25(image_fts, 10.0, 1.0, 0.5, 5.0) AS score
        FROM image_fts
        WHERE image_fts MATCH :query
        ORDER BY score
        LIMIT :limit
        """),
        {"query": match_query, "limit": limit},
    ).fetchall()

    return [(int(row[0]), float(row[1])) for row in rows]


def fts_search(db: Session, query: str, limit: int = 500) -> list[tuple[int, float]]:
    """Search images via FTS5 BM25 ranking.

    Returns list of (image_id, bm25_score) pairs sorted by relevance.
    BM25 scores from FTS5 are negative (more negative = better match).
    Porter stemmer is active, so 'forests' matches 'forest', 'mining' matches 'mine'.
    Diacritics are normalised, so 'Cepeku' matches 'Čepeku'.

    For multi-word queries, runs both:
    - AND query (all terms/phrases must match) — high-quality matches
    - OR query (any term/phrase matches) — partial matches appended after AND results

    Quoted phrases (e.g. ``"forest shrine"``) require adjacent word matching.

    Column weights: name × 10, search_text × 5, filename × 1, author × 0.5.
    User input is sanitized before passing to MATCH so special characters never
    cause silent empty results.
    """
    fts_query = _sanitize_fts_query(query.strip())
    if not fts_query:
        return []

    tokens = _parse_fts_tokens(fts_query)

    # Primary: AND query (implicit in FTS5 for space-separated terms/phrases)
    and_results = _run_fts(db, fts_query, limit)

    # Secondary: OR fallback for multi-token queries (surfaces partial matches)
    if len(tokens) >= 2:
        or_query = " OR ".join(tokens)
        or_results = _run_fts(db, or_query, limit)
        # Append OR-only results after AND results — RRF will rank AND results
        # higher since they appear earlier in the returned list.
        and_ids = {row[0] for row in and_results}
        combined = and_results + [r for r in or_results if r[0] not in and_ids]
        return combined[:limit]

    return and_results


def fts_search_terms(db: Session, terms: list[str], limit: int = 500) -> list[tuple[int, float]]:
    """Search images via FTS5 for any of the given terms (OR semantics).

    Unlike fts_search(), terms are joined with OR directly — bypassing
    _sanitize_fts_query which strips OR operators.  Each term is individually
    sanitized.  Intended for alias expansion where each term is a single token.
    """
    sanitized = [_sanitize_fts_query(t) for t in terms]
    sanitized = [t for t in sanitized if t]
    if not sanitized:
        return []
    return _run_fts(db, " OR ".join(sanitized), limit)


def fts_rebuild(db: Session) -> None:
    """Rebuild the entire FTS5 index from the images table.

    Should be called after bulk imports to ensure the index is in sync.
    Individual row changes are handled by SQLite triggers.
    """
    db.execute(text("INSERT INTO image_fts(image_fts) VALUES ('rebuild')"))
    db.commit()


def rebuild_search_text(image, db: Session) -> None:
    """Rebuild search_text for an image and flush so the FTS5 trigger fires.

    Call this after any manual tag add/remove on an image so that the FTS5
    index stays in sync.  The FTS5 image_fts_au trigger fires automatically
    on UPDATE to images, picking up the new search_text.
    """
    image.search_text = build_search_text(
        name=image.name,
        filename=image.filename,
        author=image.author,
        tags=[{"category": t.category, "value": t.value} for t in image.tags],
        subgroup=image.subgroup,
    )
    db.flush()  # triggers image_fts_au


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
            subgroup=data["sub_variant"],
        )
        db.execute(
            text("UPDATE images SET search_text = :st WHERE id = :id"),
            {"st": st, "id": img_id},
        )

    db.commit()
    logger.info("Backfilled search_text for %s images", len(images))

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
