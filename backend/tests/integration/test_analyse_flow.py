"""Integration test: analyse_upload flow (direct call, no Prefect server).

Tests that the analyse flow correctly groups files and generates preview
thumbnails. Uses a real DB (for tag categories) and real filesystem.
"""

from pathlib import Path

import pytest


@pytest.fixture
def _patch_db_for_parser(monkeypatch, tmp_db):
    """Let _build_parser() read tag categories from the test DB."""
    engine, SessionLocal = tmp_db
    db_url = str(engine.url)
    monkeypatch.setattr("backend.app.config.settings.database_url", db_url)
    return engine, SessionLocal


class TestAnalyseUpload:
    """analyse_upload flow: grouping + thumbnail generation."""

    def test_groups_detected(self, tmp_staging, _patch_db_for_parser):
        from backend.flows.ingestion import analyse_upload

        relative_paths = [
            "TestAuthor/TestMap/TestMap_Night_Grid.jpg",
            "TestAuthor/TestMap/TestMap_Summer.jpg",
            "FlatFile.jpg",
        ]

        groups = analyse_upload(
            staging_dir=str(tmp_staging),
            relative_paths=relative_paths,
        )

        assert isinstance(groups, list)
        assert len(groups) >= 1

        # The two TestMap files should be in the same group
        all_files = []
        for g in groups:
            all_files.extend(g["files"])
        assert len(all_files) == 3

        # Find the TestMap group
        testmap_group = next(
            (g for g in groups if "TestMap" in g["variant_group_name"]), None
        )
        assert testmap_group is not None
        assert len(testmap_group["files"]) == 2
        assert testmap_group["author"] == "TestAuthor"

    def test_preview_thumbnails_generated(self, tmp_staging, _patch_db_for_parser):
        from backend.flows.ingestion import analyse_upload

        relative_paths = [
            "TestAuthor/TestMap/TestMap_Night_Grid.jpg",
        ]

        groups = analyse_upload(
            staging_dir=str(tmp_staging),
            relative_paths=relative_paths,
        )

        # Check that preview thumbnails were created
        thumbs_dir = tmp_staging / ".thumbs"
        assert thumbs_dir.exists()
        thumb_files = list(thumbs_dir.glob("*.jpg"))
        assert len(thumb_files) >= 1

        # Check that the file entry has a preview_thumbnail field
        file_entry = groups[0]["files"][0]
        assert "preview_thumbnail" in file_entry
        assert file_entry["preview_thumbnail"] is not None

    def test_parsed_metadata_present(self, tmp_staging, _patch_db_for_parser):
        from backend.flows.ingestion import analyse_upload

        relative_paths = [
            "TestAuthor/TestMap/TestMap_Night_Grid.jpg",
        ]

        groups = analyse_upload(
            staging_dir=str(tmp_staging),
            relative_paths=relative_paths,
        )

        parsed = groups[0]["files"][0]["parsed"]
        assert parsed["filename"] == "TestMap_Night_Grid.jpg"
        assert parsed["gridded"] is True
        assert "tags" in parsed
