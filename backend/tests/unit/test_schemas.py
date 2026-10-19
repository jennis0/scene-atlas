"""Unit tests for Pydantic schema validation."""

import pytest
from pydantic import ValidationError

from backend.app.models.import_schemas import HashEntry, ManifestFile, ManifestRequest
from backend.app.models.schemas import (
    MAX_GROUP_EDIT_DELETES,
    AppSettings,
    AppSettingsPatch,
    GroupEditRequest,
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


class TestImportSchemas:
    def test_manifest_file_minimal(self):
        f = ManifestFile(relative_path="A/B/c.png")
        assert f.size is None and f.image_type is None

    def test_manifest_rejects_unknown_image_type(self):
        with pytest.raises(ValueError):
            ManifestFile(relative_path="a.png", image_type="portrait")

    def test_manifest_chunk_is_bounded(self):
        with pytest.raises(ValueError):
            ManifestRequest(files=[{"relative_path": f"{n}.png"} for n in range(2001)])

    def test_hash_must_be_lowercase_hex_sha256(self):
        HashEntry(item_id=1, sha256="a" * 64)
        for bad in ("A" * 64, "a" * 63, "g" * 64):
            with pytest.raises(ValueError):
                HashEntry(item_id=1, sha256=bad)


class TestGroupEditRequest:
    def test_deletions_are_bounded(self):
        body = {"base_name": "G", "images": []}
        assert GroupEditRequest(**body).delete_image_ids == []
        GroupEditRequest(**body, delete_image_ids=[1] * MAX_GROUP_EDIT_DELETES)
        with pytest.raises(ValueError):
            GroupEditRequest(**body, delete_image_ids=[1] * (MAX_GROUP_EDIT_DELETES + 1))


class TestLinkedRescanMinutes:
    def test_default_is_fifteen(self):
        assert AppSettings().linked_rescan_minutes == 15

    @pytest.mark.parametrize("value", [0, 5, 15, 60])
    def test_allowed_values(self, value):
        assert AppSettingsPatch(linked_rescan_minutes=value).linked_rescan_minutes == value

    @pytest.mark.parametrize("value", [1, 30, -5, 61])
    def test_other_values_are_rejected(self, value):
        with pytest.raises(ValidationError):
            AppSettingsPatch(linked_rescan_minutes=value)
