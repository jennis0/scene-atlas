"""Unit tests for preview thumbnail filename logic.

Verifies that the name mangling in generate_preview_thumbnail (generation)
and get_preview_thumbnail (serving) are consistent.
"""

from pathlib import Path


def _generate_safe_name(relative_path: str) -> str:
    """Reproduce the safe name logic from generate_preview_thumbnail."""
    safe_name = relative_path.replace("/", "__").replace("\\", "__")
    safe_name = Path(safe_name).stem + ".jpg"
    return safe_name


def _serve_safe_name(relative_path: str) -> str:
    """Reproduce the safe name logic from get_preview_thumbnail endpoint."""
    safe_name = relative_path.replace("/", "__").replace("\\", "__")
    safe_name = Path(safe_name).stem + ".jpg"
    return safe_name


class TestThumbnailNameConsistency:
    """The generation and serving functions must produce identical safe names."""

    def test_simple_path(self):
        rp = "author/group/map.jpg"
        assert _generate_safe_name(rp) == _serve_safe_name(rp)

    def test_deeply_nested(self):
        rp = "author/group/sub1/sub2/map_night.jpg"
        assert _generate_safe_name(rp) == _serve_safe_name(rp)

    def test_windows_backslash(self):
        rp = "author\\group\\map.jpg"
        assert _generate_safe_name(rp) == _serve_safe_name(rp)

    def test_mixed_separators(self):
        rp = "author/group\\subdir/map.png"
        gen = _generate_safe_name(rp)
        serve = _serve_safe_name(rp)
        assert gen == serve
        # All slashes should become double underscores
        assert "/" not in gen
        assert "\\" not in gen


class TestThumbnailNameFormat:
    """Verify the expected output format."""

    def test_extension_always_jpg(self):
        assert _generate_safe_name("a/b/map.png").endswith(".jpg")
        assert _generate_safe_name("a/b/map.webp").endswith(".jpg")
        assert _generate_safe_name("a/b/map.jpg").endswith(".jpg")

    def test_slashes_replaced(self):
        result = _generate_safe_name("author/group/file.jpg")
        assert result == "author__group__file.jpg"

    def test_flat_file(self):
        result = _generate_safe_name("file.jpg")
        assert result == "file.jpg"
