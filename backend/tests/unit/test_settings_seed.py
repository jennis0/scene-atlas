"""Tests for seed_default_settings WebP env var handling."""

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


class TestWebPSeed:
    def test_convert_to_webp_defaults_true(self, fresh_db):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CONVERT_TO_WEBP", None)
            seed_default_settings(fresh_db)
        row = fresh_db.query(AppSetting).filter_by(key="convert_to_webp").first()
        assert row is not None
        assert json.loads(row.value_json) is True

    def test_convert_to_webp_false_from_env(self, fresh_db):
        with patch.dict(os.environ, {"CONVERT_TO_WEBP": "0"}):
            seed_default_settings(fresh_db)
        row = fresh_db.query(AppSetting).filter_by(key="convert_to_webp").first()
        assert json.loads(row.value_json) is False

    def test_convert_to_webp_true_from_env(self, fresh_db):
        with patch.dict(os.environ, {"CONVERT_TO_WEBP": "1"}):
            seed_default_settings(fresh_db)
        row = fresh_db.query(AppSetting).filter_by(key="convert_to_webp").first()
        assert json.loads(row.value_json) is True

    def test_seed_is_noop_if_rows_exist(self, fresh_db):
        # Pre-populate — seed should be a no-op and must not overwrite existing values
        fresh_db.add(AppSetting(key="convert_to_webp", value_json="false"))
        fresh_db.commit()
        seed_default_settings(fresh_db)
        count = fresh_db.query(AppSetting).count()
        assert count == 1
        row = fresh_db.query(AppSetting).filter_by(key="convert_to_webp").first()
        assert json.loads(row.value_json) is False, "seed must not overwrite existing values"
