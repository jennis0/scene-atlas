"""Tests for seed_default_settings function."""

import json

from backend.app.models.database import AppSetting, seed_default_settings


def test_seed_includes_max_concurrent_heavy_requests(db_session):
    """max_concurrent_heavy_requests must be present in the seeded DB."""
    seed_default_settings(db_session)
    row = db_session.query(AppSetting).filter_by(key="max_concurrent_heavy_requests").first()
    assert row is not None
    assert isinstance(json.loads(row.value_json), int)


def test_seed_includes_all_import_limits(db_session):
    """Import limits must all be present in the seeded DB."""
    seed_default_settings(db_session)
    for key in (
        "max_import_file_size",
        "max_video_file_size",
        "max_import_files",
        "max_import_total_size",
    ):
        row = db_session.query(AppSetting).filter_by(key=key).first()
        assert row is not None, f"Missing seed key: {key}"


def test_seed_skips_on_existing_db(db_session):
    """seed_default_settings does nothing if DB already has rows."""
    seed_default_settings(db_session)
    row = db_session.query(AppSetting).filter_by(key="max_import_files").first()
    row.value_json = json.dumps(9999)
    db_session.commit()

    seed_default_settings(db_session)  # Should not overwrite

    row2 = db_session.query(AppSetting).filter_by(key="max_import_files").first()
    assert json.loads(row2.value_json) == 9999


def test_seed_uses_resource_defaults(db_session):
    """Concurrency settings should use resource_detector values."""
    from unittest.mock import patch

    # Mock resource_detector to return known values
    with patch("backend.app.resource_detector.compute_resource_defaults") as mock_compute:
        mock_compute.return_value = {
            "max_job_workers": 42,
            "max_concurrent_prepare": 99,
            "max_concurrent_heavy_requests": 7,
        }

        seed_default_settings(db_session)

    # Verify the seeded values match the mocked resource_defaults
    assert (
        json.loads(db_session.query(AppSetting).filter_by(key="max_job_workers").first().value_json)
        == 42
    )
    assert (
        json.loads(
            db_session.query(AppSetting).filter_by(key="max_concurrent_prepare").first().value_json
        )
        == 99
    )
    assert (
        json.loads(
            db_session.query(AppSetting)
            .filter_by(key="max_concurrent_heavy_requests")
            .first()
            .value_json
        )
        == 7
    )


def test_seed_matches_schema_defaults(db_session, monkeypatch):
    """The seed covers every AppSettings field and uses its defaults, so the two can't drift."""
    from backend.app.models.schemas import AppSettings

    monkeypatch.delenv("CONVERT_TO_WEBP", raising=False)
    seed_default_settings(db_session)
    seeded = {row.key: json.loads(row.value_json) for row in db_session.query(AppSetting)}
    expected = AppSettings().model_dump(exclude={"active_model"})
    assert seeded.keys() == expected.keys()
    resource_keys = {"max_concurrent_prepare", "max_concurrent_heavy_requests", "max_job_workers"}
    for key in expected.keys() - resource_keys:
        assert seeded[key] == expected[key], key
    assert seeded["max_import_file_size"] == 2 * 1024 * 1024 * 1024
