"""Tests must never touch the developer's real library in ./data."""

from pathlib import Path

from backend.app.config import settings

REPO_DATA = Path(__file__).resolve().parents[3] / "data"


def test_storage_roots_are_outside_the_repo_data_dir():
    for root in (settings.data_dir, settings.images_dir):
        assert not Path(root).resolve().is_relative_to(REPO_DATA.resolve())
