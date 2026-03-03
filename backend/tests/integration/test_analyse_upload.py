"""Integration test: analyse_upload (direct call).

Tests that the analyse flow correctly groups files, computes content hashes,
and detects duplicates. Uses a real DB (for tag categories) and real filesystem.
"""

import json

import pytest


@pytest.fixture
def _patch_db_for_parser(monkeypatch, tmp_db):
    """Let _build_parser() read tag categories from the test DB."""
    engine, SessionLocal = tmp_db
    db_url = str(engine.url)
    monkeypatch.setattr("backend.app.config.settings.database_url", db_url)
    return engine, SessionLocal


def _load_test_file_map(staging_dir):
    """Load .file_map.json from a staging directory."""
    map_path = staging_dir / ".file_map.json"
    if map_path.exists():
        return json.loads(map_path.read_text())
    return {}


class TestAnalyseUpload:
    """analyse_upload flow: grouping, hash computation, and duplicate detection."""

    def test_groups_detected(self, tmp_staging, _patch_db_for_parser):
        from backend.pipeline.ingestion import analyse_upload

        file_map = _load_test_file_map(tmp_staging)
        relative_paths = [
            "TestAuthor/TestMap/TestMap_Night_Grid.jpg",
            "TestAuthor/TestMap/TestMap_Summer.jpg",
            "FlatFile.jpg",
        ]

        groups = analyse_upload(
            staging_dir=str(tmp_staging),
            relative_paths=relative_paths,
            file_map=file_map,
        )

        assert isinstance(groups, list)
        assert len(groups) >= 1

        # The two TestMap files should be in the same group
        all_files = []
        for g in groups:
            all_files.extend(g["files"])
        assert len(all_files) == 3

        # Find the TestMap group (parser cleans CamelCase → "Test Map")
        testmap_group = next(
            (g for g in groups if "Test Map" in g["group_name"]),
            None,
        )
        assert testmap_group is not None
        assert len(testmap_group["files"]) == 2
        assert testmap_group["author"] == "TestAuthor"

    def test_content_hash_computed(self, tmp_staging, _patch_db_for_parser):
        """analyse_upload computes a SHA-256 content_hash for each staged file."""
        from backend.pipeline.ingestion import analyse_upload

        file_map = _load_test_file_map(tmp_staging)
        relative_paths = [
            "TestAuthor/TestMap/TestMap_Night_Grid.jpg",
        ]

        groups = analyse_upload(
            staging_dir=str(tmp_staging),
            relative_paths=relative_paths,
            file_map=file_map,
        )

        file_entry = groups[0]["files"][0]
        assert "content_hash" in file_entry
        # SHA-256 hex digest is 64 characters
        assert file_entry["content_hash"] is not None
        assert len(file_entry["content_hash"]) == 64

    def test_parsed_metadata_present(self, tmp_staging, _patch_db_for_parser):
        from backend.pipeline.ingestion import analyse_upload

        file_map = _load_test_file_map(tmp_staging)
        relative_paths = [
            "TestAuthor/TestMap/TestMap_Night_Grid.jpg",
        ]

        groups = analyse_upload(
            staging_dir=str(tmp_staging),
            relative_paths=relative_paths,
            file_map=file_map,
        )

        parsed = groups[0]["files"][0]["parsed"]
        assert parsed["filename"] == "TestMap_Night_Grid.jpg"
        assert parsed["gridded"] is True
        assert "tags" in parsed
