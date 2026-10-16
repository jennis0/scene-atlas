"""Unit tests for backend.pipeline.naming."""

from types import SimpleNamespace

from backend.pipeline.naming import (
    download_filename,
    export_metadata,
    export_path,
    sanitize_segment,
    unique_export_path,
)


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


# Helper to create mock Image objects without needing the real ORM model
def _mock_image(**kwargs):
    defaults = {
        "name": "Forest Map",
        "filename": "Forest_Map.jpg",
        "subgroup": None,
        "gridded": False,
        "grid_type": None,
        "grid_width": None,
        "grid_height": None,
        "image_type": "battlemap",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestDownloadFilename:
    """Tests for download_filename()."""

    def test_basic_no_grid(self):
        img = _mock_image(name="Forest Map", gridded=False)
        result = download_filename(img, "Forest Map")
        # group_name == img.name → group not included
        assert result == "Forest Map - No Grid.jpg"

    def test_with_square_grid_dimensions(self):
        img = _mock_image(gridded=True, grid_width=20, grid_height=15)
        result = download_filename(img, "Forest Map")
        assert result == "Forest Map - Grid 20x15.jpg"

    def test_with_hex_grid(self):
        img = _mock_image(gridded=True, grid_type="hex", grid_width=10, grid_height=8)
        result = download_filename(img, "Forest Map")
        assert result == "Forest Map - Hex 10x8.jpg"

    def test_grid_without_dimensions(self):
        img = _mock_image(gridded=True, grid_width=None, grid_height=None)
        result = download_filename(img, "Forest Map")
        assert result == "Forest Map - Grid.jpg"

    def test_with_group_name_different_from_image_name(self):
        img = _mock_image(name="Night Variant", gridded=False)
        result = download_filename(img, "Forest Map")
        assert result == "Forest Map - Night Variant - No Grid.jpg"

    def test_with_subgroup(self):
        img = _mock_image(
            name="Night Variant", subgroup="Gridded", gridded=True, grid_width=24, grid_height=16
        )
        result = download_filename(img, "Forest Map")
        assert result == "Forest Map - Gridded - Night Variant - Grid 24x16.jpg"

    def test_preserves_extension(self):
        img = _mock_image(filename="map.png", gridded=False)
        result = download_filename(img, "Forest Map")
        assert result.endswith(".png")

    def test_unsafe_chars_sanitized(self):
        img = _mock_image(name="Map: Night/Day", gridded=False)
        result = download_filename(img, "Author/Pack")
        assert "/" not in result.split(".")[0]
        assert ":" not in result


class TestExportPath:
    """Tests for export_path()."""

    def test_grouped_image(self):
        img = _mock_image(gridded=False)
        result = export_path(img, "Forest Map", "AuthorA")
        assert result == "AuthorA/Forest Map/Forest Map - No Grid.jpg"

    def test_grouped_with_subgroup(self):
        img = _mock_image(
            name="Night", subgroup="Gridded", gridded=True, grid_width=20, grid_height=15
        )
        result = export_path(img, "Forest Map", "AuthorA")
        assert result == "AuthorA/Forest Map/Gridded/Forest Map - Gridded - Night - Grid 20x15.jpg"

    def test_ungrouped_image(self):
        img = _mock_image(gridded=False)
        result = export_path(img, None, "AuthorA")
        assert result == "AuthorA/_Ungrouped/Forest Map - No Grid.jpg"

    def test_missing_author(self):
        img = _mock_image(gridded=False)
        result = export_path(img, "Group", None)
        assert result.startswith("Unknown/")

    def test_empty_author(self):
        img = _mock_image(gridded=False)
        result = export_path(img, "Group", "  ")
        assert result.startswith("Unknown/")

    def test_author_with_unsafe_chars(self):
        img = _mock_image(gridded=False)
        result = export_path(img, "Group", "Author:Name")
        assert result.startswith("Author Name/")


def _exportable(**kwargs):
    group = kwargs.pop("group", SimpleNamespace(base_name="Forest Map"))
    return _mock_image(group=group, author="AuthorA", tags=[], **kwargs)


class TestUniqueExportPath:
    def test_first_use_is_unchanged_and_recorded(self):
        seen: set[str] = set()
        arc = unique_export_path(_exportable(), seen)
        assert arc == "AuthorA/Forest Map/Forest Map - No Grid.jpg"
        assert seen == {arc}

    def test_collisions_get_numbered_suffixes(self):
        seen: set[str] = set()
        arcs = [unique_export_path(_exportable(), seen) for _ in range(3)]
        assert arcs == [
            "AuthorA/Forest Map/Forest Map - No Grid.jpg",
            "AuthorA/Forest Map/Forest Map - No Grid (2).jpg",
            "AuthorA/Forest Map/Forest Map - No Grid (3).jpg",
        ]

    def test_ungrouped_image(self):
        assert unique_export_path(_exportable(group=None), set()).startswith("AuthorA/_Ungrouped/")


class TestExportMetadata:
    def test_groups_tags_by_category(self):
        tags = [
            SimpleNamespace(category="biome", value="forest"),
            SimpleNamespace(category="biome", value="swamp"),
            SimpleNamespace(category="mood", value="dark"),
        ]
        meta = export_metadata(
            _mock_image(tags=tags, gridded=True, grid_type="square", grid_width=20, grid_height=15)
        )
        assert meta == {
            "image_type": "battlemap",
            "gridded": True,
            "grid_type": "square",
            "grid_width": 20,
            "grid_height": 15,
            "tags": {"biome": ["forest", "swamp"], "mood": ["dark"]},
        }

    def test_missing_type_defaults_to_battlemap(self):
        assert export_metadata(_mock_image(image_type=None, tags=[]))["image_type"] == "battlemap"
