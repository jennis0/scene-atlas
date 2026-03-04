"""Unit tests for FileError schema backward compatibility and new fields."""

from backend.app.models.schemas import FileError


class TestFileErrorBackwardCompat:
    """Old error dicts without relative_path/severity should get Pydantic defaults."""

    def test_old_format_without_new_fields(self):
        """Pre-existing error dicts with only filename/reason/stage still work."""
        data = {"filename": "image.png", "reason": "Corrupt file", "stage": "parse"}
        error = FileError(**data)
        assert error.filename == "image.png"
        assert error.reason == "Corrupt file"
        assert error.stage == "parse"
        assert error.relative_path is None
        assert error.severity == "error"

    def test_new_format_with_all_fields(self):
        """New error dicts with relative_path and severity work."""
        data = {
            "filename": "image.png",
            "relative_path": "maps/forest/image.png",
            "reason": "Could not generate embedding",
            "stage": "embedding",
            "severity": "warning",
        }
        error = FileError(**data)
        assert error.relative_path == "maps/forest/image.png"
        assert error.severity == "warning"

    def test_severity_defaults_to_error(self):
        """When severity is omitted, it defaults to 'error'."""
        error = FileError(filename="x.png", reason="bad", stage="parse")
        assert error.severity == "error"

    def test_relative_path_defaults_to_none(self):
        """When relative_path is omitted, it defaults to None."""
        error = FileError(filename="x.png", reason="bad", stage="parse")
        assert error.relative_path is None

    def test_json_round_trip(self):
        """FileError can be serialized and deserialized from JSON (as stored in DB)."""
        import json

        original = FileError(
            filename="img.png",
            relative_path="a/b/img.png",
            reason="Qdrant failure",
            stage="qdrant_save",
            severity="warning",
        )
        json_str = original.model_dump_json()
        restored = FileError(**json.loads(json_str))
        assert restored == original

    def test_old_json_without_new_fields_deserializes(self):
        """Simulates reading old JSON from the DB that lacks new fields."""
        import json

        old_json = json.dumps({"filename": "x.png", "reason": "fail", "stage": "copy"})
        error = FileError(**json.loads(old_json))
        assert error.relative_path is None
        assert error.severity == "error"
