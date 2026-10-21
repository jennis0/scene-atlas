"""Unit tests for the system info helpers (backend/app/api/system.py).

Tests the _dir_size() and _distinct_roots() helpers in isolation — no DB or API needed.
"""

import os
from pathlib import Path

from backend.app.api.system import _dir_size, _distinct_roots


class TestDirSize:
    """Tests for _dir_size() recursive directory size calculation."""

    def test_empty_dir(self, tmp_path: Path):
        assert _dir_size(tmp_path) == 0

    def test_single_file(self, tmp_path: Path):
        f = tmp_path / "file.txt"
        f.write_bytes(b"x" * 100)
        assert _dir_size(tmp_path) == 100

    def test_multiple_files(self, tmp_path: Path):
        (tmp_path / "a.bin").write_bytes(b"a" * 50)
        (tmp_path / "b.bin").write_bytes(b"b" * 75)
        assert _dir_size(tmp_path) == 125

    def test_nested_directories(self, tmp_path: Path):
        sub = tmp_path / "level1" / "level2"
        sub.mkdir(parents=True)
        (tmp_path / "root.bin").write_bytes(b"r" * 10)
        (sub / "deep.bin").write_bytes(b"d" * 30)
        assert _dir_size(tmp_path) == 40

    def test_missing_directory(self, tmp_path: Path):
        """Should return 0 for a non-existent path, not raise."""
        assert _dir_size(tmp_path / "does_not_exist") == 0

    def test_permission_error(self, tmp_path: Path, monkeypatch):
        """Should return 0 if os.scandir raises PermissionError."""

        def _raise(*args, **kwargs):
            raise PermissionError("no access")

        monkeypatch.setattr(os, "scandir", _raise)
        assert _dir_size(tmp_path) == 0


class TestDistinctRoots:
    """The storage total counts each byte once however the two roots overlap."""

    def test_separate_roots(self, tmp_path: Path):
        data, images = tmp_path / "data", tmp_path / "images"
        assert _distinct_roots(data, images) == [data.resolve(), images.resolve()]

    def test_same_folder_for_both(self, tmp_path: Path):
        assert _distinct_roots(tmp_path, tmp_path) == [tmp_path.resolve()]

    def test_library_inside_data(self, tmp_path: Path):
        """The server default when only SCENE_ATLAS_DATA_DIR is set."""
        assert _distinct_roots(tmp_path, tmp_path / "images") == [tmp_path.resolve()]

    def test_data_inside_library(self, tmp_path: Path):
        assert _distinct_roots(tmp_path / "data", tmp_path) == [tmp_path.resolve()]

    def test_sibling_with_shared_prefix_is_not_inside(self, tmp_path: Path):
        data, images = tmp_path / "data", tmp_path / "data-images"
        assert _distinct_roots(data, images) == [data.resolve(), images.resolve()]
