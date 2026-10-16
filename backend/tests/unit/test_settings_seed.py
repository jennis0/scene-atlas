"""Tests for seed_default_settings storage-format env var handling."""

import json
import os
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.database import AppSetting, Base, seed_default_settings


@pytest.fixture
def fresh_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()


class TestStoredFormatSeed:
    def test_defaults_to_original(self, fresh_db):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CONVERT_TO_WEBP", None)
            seed_default_settings(fresh_db)
        row = fresh_db.query(AppSetting).filter_by(key="stored_format").first()
        assert row is not None
        assert json.loads(row.value_json) == "original"

    def test_original_when_env_is_off(self, fresh_db):
        with patch.dict(os.environ, {"CONVERT_TO_WEBP": "0"}):
            seed_default_settings(fresh_db)
        row = fresh_db.query(AppSetting).filter_by(key="stored_format").first()
        assert json.loads(row.value_json) == "original"

    def test_webp_when_env_is_on(self, fresh_db):
        with patch.dict(os.environ, {"CONVERT_TO_WEBP": "1"}):
            seed_default_settings(fresh_db)
        row = fresh_db.query(AppSetting).filter_by(key="stored_format").first()
        assert json.loads(row.value_json) == "webp"

    def test_seed_is_noop_if_rows_exist(self, fresh_db):
        # Pre-populate — seed should be a no-op and must not overwrite existing values
        fresh_db.add(AppSetting(key="stored_format", value_json='"png"'))
        fresh_db.commit()
        seed_default_settings(fresh_db)
        count = fresh_db.query(AppSetting).count()
        assert count == 1
        row = fresh_db.query(AppSetting).filter_by(key="stored_format").first()
        assert json.loads(row.value_json) == "png", "seed must not overwrite existing values"
