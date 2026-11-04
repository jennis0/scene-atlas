"""``naming.sanitize_segment``; the readable layout is in test_readable_layout.py."""

from backend.pipeline.naming import sanitize_segment


class TestSanitizeSegment:
    """Tests for sanitize_segment()."""

    def test_no_change_for_safe_string(self):
        assert sanitize_segment("Hello World") == "Hello World"

    def test_replaces_slash(self):
        assert sanitize_segment("Author/Name") == "Author Name"

    def test_replaces_backslash(self):
        assert sanitize_segment("Author\\Name") == "Author Name"

    def test_replaces_colon(self):
        assert sanitize_segment("Map: Night") == "Map Night"

    def test_replaces_asterisk(self):
        assert sanitize_segment("Map*v2") == "Map v2"

    def test_replaces_question_mark(self):
        assert sanitize_segment("What?") == "What"

    def test_replaces_angle_brackets(self):
        assert sanitize_segment("<Map>") == "Map"

    def test_replaces_pipe(self):
        assert sanitize_segment("Left|Right") == "Left Right"

    def test_replaces_double_quote(self):
        assert sanitize_segment('The "Best" Map') == "The Best Map"

    def test_collapses_whitespace(self):
        assert sanitize_segment("Too   Many   Spaces") == "Too Many Spaces"

    def test_strips_leading_trailing_whitespace(self):
        assert sanitize_segment("  Hello  ") == "Hello"

    def test_multiple_unsafe_chars(self):
        assert sanitize_segment('A/B\\C:D*E?"F<G>H|I') == "A B C D E F G H I"

    def test_empty_string(self):
        assert sanitize_segment("") == ""

    def test_control_characters(self):
        assert sanitize_segment("Bad\x00\x1fName") == "Bad Name"
