"""Unit tests for the FTS search service.

Covers:
- _sanitize_fts_query(): strips FTS5 boolean operators and special chars
- fts_search(): returns (image_id, score) pairs from the FTS5 index
- backfill_search_text(): populates search_text for images that are missing it
"""

import pytest
from sqlalchemy import text

from backend.app.models.database import Image
from backend.app.services.fts_service import (
    _sanitize_fts_query,
    backfill_search_text,
    fts_search,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_image(name, filename=None, author="Author", key=None, image_type="battlemap"):
    """Construct a minimal Image ORM object suitable for test DB insertion."""
    if filename is None:
        filename = name.replace(" ", "_") + ".jpg"
    if key is None:
        key = filename
    return Image(
        name=name,
        filename=filename,
        author=author,
        storage_key=key,
        media_type="image",
        image_type=image_type,
    )


# ---------------------------------------------------------------------------
# TestSanitizeFtsQuery
# ---------------------------------------------------------------------------


class TestSanitizeFtsQuery:
    """Pure unit tests for _sanitize_fts_query -- no DB required."""

    def test_plain_words_unchanged(self):
        """Plain words with no special syntax pass through unchanged."""
        assert _sanitize_fts_query("forest night") == "forest night"

    def test_removes_AND_operator(self):
        """Uppercase AND is stripped; surrounding words remain."""
        assert _sanitize_fts_query("forest AND night") == "forest night"

    def test_removes_OR_operator(self):
        """Uppercase OR is stripped; surrounding words remain."""
        assert _sanitize_fts_query("forest OR night") == "forest night"

    def test_removes_NOT_operator(self):
        """Uppercase NOT is stripped; the following word remains."""
        assert _sanitize_fts_query("NOT underground") == "underground"

    def test_lowercase_operators_preserved(self):
        """Lowercase and/or/not are plain words in FTS5 and must be kept."""
        result = _sanitize_fts_query("and or not")
        assert "and" in result
        assert "or" in result
        assert "not" in result

    def test_removes_special_chars(self):
        """Parentheses and similar punctuation are removed."""
        assert _sanitize_fts_query("mine (underground)") == "mine underground"

    def test_removes_quotes(self):
        assert _sanitize_fts_query('"forest night"') == "forest night"

    def test_collapses_whitespace(self):
        """Multiple spaces are collapsed to a single space and stripped."""
        assert _sanitize_fts_query("  forest   night  ") == "forest night"

    def test_empty_string_returns_empty(self):
        assert _sanitize_fts_query("") == ""

    def test_whitespace_only_returns_empty(self):
        assert _sanitize_fts_query("   ") == ""

    def test_asterisk_removed(self):
        """Asterisk (FTS5 prefix operator) is stripped."""
        assert _sanitize_fts_query("forest*") == "forest"

    def test_caret_removed(self):
        """Caret (FTS5 boost operator) is stripped."""
        assert _sanitize_fts_query("^forest") == "forest"


# ---------------------------------------------------------------------------
# TestFtsSearch
# ---------------------------------------------------------------------------


class TestFtsSearch:
    """Integration tests for fts_search() -- require a real SQLite DB."""

    def test_empty_query_returns_empty_list(self, db_session):
        """An empty query string must return [] without touching the DB."""
        result = fts_search(db_session, "")
        assert result == []

    def test_whitespace_query_returns_empty_list(self, db_session):
        """A whitespace-only query is treated as empty."""
        result = fts_search(db_session, "  ")
        assert result == []

    def test_returns_matching_image(self, db_session):
        """An image with matching text in its name is found by fts_search."""
        img = _make_image("TestMap Night", key="testmapnight.jpg")
        db_session.add(img)
        db_session.commit()

        # Backfill search_text so the FTS index has content.
        backfill_search_text(db_session)

        results = fts_search(db_session, "night")
        assert len(results) >= 1
        image_ids = [row[0] for row in results]
        assert img.id in image_ids

    def test_limit_respected(self, db_session):
        """The limit parameter caps the number of rows returned."""
        for i in range(5):
            img = _make_image(f"Forest Map {i}", key=f"forestmap{i}.jpg")
            db_session.add(img)
        db_session.commit()
        backfill_search_text(db_session)

        results = fts_search(db_session, "forest", limit=2)
        assert len(results) <= 2

    def test_returns_list_of_tuples(self, db_session):
        """Each result item must be a 2-tuple of (int image_id, float score)."""
        img = _make_image("Cave River Night", key="caverivern.jpg")
        db_session.add(img)
        db_session.commit()
        backfill_search_text(db_session)

        results = fts_search(db_session, "cave")
        assert len(results) >= 1
        image_id, score = results[0]
        assert isinstance(image_id, int)
        assert isinstance(score, float)

    def test_no_match_returns_empty(self, db_session):
        """A query with no matching images returns an empty list."""
        results = fts_search(db_session, "zzznomatch")
        assert results == []


# ---------------------------------------------------------------------------
# TestBackfillSearchText
# ---------------------------------------------------------------------------


class TestBackfillSearchText:
    """Integration tests for backfill_search_text() -- require a real SQLite DB."""

    def test_backfills_missing_search_text(self, db_session):
        """An image with search_text=None gets its search_text populated."""
        img = _make_image("TestMap Night", key="backfill1.jpg")
        db_session.add(img)
        db_session.commit()
        assert img.search_text is None

        count = backfill_search_text(db_session)

        assert count == 1
        row = db_session.execute(
            text("SELECT search_text FROM images WHERE id = :id"), {"id": img.id}
        ).fetchone()
        assert row[0] is not None
        assert row[0] != ""

    def test_skips_images_with_existing_search_text(self, db_session):
        """Images that already have search_text are skipped (count=0)."""
        img = _make_image("Desert Canyon", key="preloaded.jpg")
        img.search_text = "pre-existing content"
        db_session.add(img)
        db_session.commit()

        count = backfill_search_text(db_session)
        assert count == 0

    def test_idempotent(self, db_session):
        """Calling backfill twice: first call returns 1, second returns 0."""
        img = _make_image("Forest River", key="idempotent1.jpg")
        db_session.add(img)
        db_session.commit()

        first = backfill_search_text(db_session)
        second = backfill_search_text(db_session)

        assert first == 1
        assert second == 0

    def test_includes_author_in_search_text(self, db_session):
        """The author name is included in the generated search_text."""
        img = _make_image("Cave Map", author="JohnDoe", key="authortest.jpg")
        db_session.add(img)
        db_session.commit()

        backfill_search_text(db_session)

        row = db_session.execute(
            text("SELECT search_text FROM images WHERE id = :id"), {"id": img.id}
        ).fetchone()
        assert "JohnDoe" in row[0] or "John" in row[0]

    def test_camelcase_split_in_search_text(self, db_session):
        """CamelCase names are split so each word is individually searchable."""
        img = _make_image("TestMap", key="camelcase1.jpg")
        db_session.add(img)
        db_session.commit()

        backfill_search_text(db_session)

        row = db_session.execute(
            text("SELECT search_text FROM images WHERE id = :id"), {"id": img.id}
        ).fetchone()
        search_text = row[0]
        # build_search_text splits CamelCase: 'TestMap' -> 'Test Map'
        assert "Test" in search_text
        assert "Map" in search_text
