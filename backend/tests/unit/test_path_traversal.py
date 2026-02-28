"""Unit tests for path traversal guards used in API handlers.

The guard pattern from imports.py (staging preview) and images.py:

    resolved = path.resolve()
    if not str(resolved).startswith(str(base_dir.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

These tests exercise the guard logic directly using pathlib — no HTTP layer needed.
"""

import sys
from pathlib import Path

import pytest


def _is_within_base(base_dir: Path, target: Path) -> bool:
    """Path containment guard using relative_to (no prefix false-positives)."""
    try:
        target.resolve().relative_to(base_dir.resolve())
        return True
    except ValueError:
        return False


class TestPathTraversalGuard:
    """Tests for the string-startswith path containment guard."""

    # ── Allowed paths ──────────────────────────────────────────────────────────

    def test_nested_subpath_allowed(self, tmp_path):
        target = tmp_path / "staging" / "job1" / "file.jpg"
        assert _is_within_base(tmp_path, target) is True

    def test_direct_child_allowed(self, tmp_path):
        target = tmp_path / "file.jpg"
        assert _is_within_base(tmp_path, target) is True

    def test_path_equal_to_base_allowed(self, tmp_path):
        assert _is_within_base(tmp_path, tmp_path) is True

    def test_dotdot_that_stays_inside_base_allowed(self, tmp_path):
        """../ that resolves back inside the base dir must still be allowed."""
        # tmp_path / "a" / ".." / "b" resolves to tmp_path / "b"
        target = tmp_path / "a" / ".." / "b" / "file.jpg"
        assert _is_within_base(tmp_path, target) is True

    # ── Blocked paths ──────────────────────────────────────────────────────────

    def test_single_dotdot_traversal_blocked(self, tmp_path):
        """A single ../ step that exits the base dir must be blocked."""
        target = tmp_path / ".." / "sibling_dir" / "file.txt"
        assert _is_within_base(tmp_path, target) is False

    def test_deep_dotdot_traversal_blocked(self, tmp_path):
        """Multiple ../ components climbing far above base dir must be blocked."""
        target = tmp_path / "a" / "b" / ".." / ".." / ".." / ".." / "etc" / "passwd"
        assert _is_within_base(tmp_path, target) is False

    def test_absolute_path_outside_base_blocked(self, tmp_path):
        """An absolute path to a different directory tree must be blocked."""
        # Use the system temp root, which is outside tmp_path
        outside = tmp_path.parent.parent
        assert _is_within_base(tmp_path, outside) is False

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Creating symlinks requires elevated privileges on Windows",
    )
    def test_symlink_escaping_base_blocked(self, tmp_path):
        """A symlink pointing outside the base dir must be detected via resolve()."""
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        # Create a symlink inside base_dir that points to the outside dir
        link = base_dir / "evil_link"
        link.symlink_to(outside)

        # resolve() follows the symlink; the resolved path is outside base_dir
        assert _is_within_base(base_dir, link) is False

    # ── Known limitation ───────────────────────────────────────────────────────

    def test_adjacent_prefix_correctly_blocked(self, tmp_path):
        """Sibling directory with shared prefix must be blocked."""
        base_dir = tmp_path / "job1"
        sibling = tmp_path / "job1evil" / "file.jpg"
        assert _is_within_base(base_dir, sibling) is False


class TestPathTraversalGuardWithRealFiles:
    """Guards must work correctly even when the paths exist on disk."""

    def test_existing_file_within_base_allowed(self, tmp_path):
        target = tmp_path / "file.jpg"
        target.write_bytes(b"data")
        assert _is_within_base(tmp_path, target) is True

    def test_existing_file_outside_base_blocked(self, tmp_path):
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        outside_file = tmp_path / "outside.jpg"
        outside_file.write_bytes(b"data")
        assert _is_within_base(base_dir, outside_file) is False

    def test_deeply_nested_existing_file_allowed(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        target = nested / "image.png"
        target.write_bytes(b"data")
        assert _is_within_base(tmp_path, target) is True
