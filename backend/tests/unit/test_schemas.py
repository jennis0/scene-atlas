"""Unit tests for Pydantic schema validation."""

import pytest

from backend.app.models.schemas import (
    ImportConfirmFile,
    ImportConfirmRequest,
    TagBase,
)


class TestTagBase:
    """TagBase schema validation and defaults."""

    def test_defaults(self):
        tag = TagBase(category="lighting", value="night")
        assert tag.confidence == 1.0
        assert tag.source == "manual"

    def test_explicit_values(self):
        tag = TagBase(category="season", value="winter", confidence=0.8, source="auto")
        assert tag.confidence == 0.8
        assert tag.source == "auto"

    def test_round_trip_dict(self):
        tag = TagBase(category="terrain", value="forest", confidence=0.9, source="auto")
        d = tag.model_dump()
        restored = TagBase(**d)
        assert restored == tag

    def test_round_trip_json(self):
        tag = TagBase(category="weather", value="rain", confidence=0.7, source="auto")
        json_str = tag.model_dump_json()
        restored = TagBase.model_validate_json(json_str)
        assert restored == tag


class TestImportConfirmFile:
    """ImportConfirmFile defaults and validation."""

    def test_minimal(self):
        f = ImportConfirmFile(relative_path="author/map.jpg")
        assert f.tags == []
        assert f.gridded is None
        assert f.grid_width is None
        assert f.grid_height is None
        assert f.subgroup is None

    def test_with_tags(self):
        f = ImportConfirmFile(
            relative_path="author/map.jpg",
            tags=[TagBase(category="lighting", value="night")],
            gridded=True,
            grid_width=30,
            grid_height=30,
            subgroup="Night",
        )
        assert len(f.tags) == 1
        assert f.gridded is True

    def test_serialization_for_flow(self):
        """model_dump() output should be compatible with process_import_group's files param."""
        f = ImportConfirmFile(
            relative_path="author/map.jpg",
            tags=[TagBase(category="lighting", value="night", confidence=0.9, source="auto")],
            gridded=True,
        )
        d = f.model_dump()
        assert d["relative_path"] == "author/map.jpg"
        assert d["tags"][0]["category"] == "lighting"
        assert d["tags"][0]["value"] == "night"
        assert d["gridded"] is True


class TestImportConfirmRequest:
    """ImportConfirmRequest validation."""

    def test_valid_request(self):
        req = ImportConfirmRequest(
            author="TestAuthor",
            group_name="Test Map",
            files=[ImportConfirmFile(relative_path="file.jpg")],
        )
        assert req.author == "TestAuthor"
        assert len(req.files) == 1

    def test_missing_author_fails(self):
        with pytest.raises(ValueError):
            ImportConfirmRequest(
                group_name="Test Map",
                files=[ImportConfirmFile(relative_path="file.jpg")],
            )
