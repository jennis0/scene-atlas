"""Unit tests for Pydantic schema validation."""

import pytest

from backend.app.models.import_schemas import HashEntry, ManifestFile, ManifestRequest
from backend.app.models.schemas import TagBase


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
