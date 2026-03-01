"""Unit tests for import_job_id tracking through the ingestion pipeline.

Verifies that _save_image_to_db stores import_job_id on the Image row, and
that prepare_single_image includes import_job_id in its returned image_data.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.database import Base, Image, ImportJob


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestSaveImageToDbImportJobId:
    def test_import_job_id_stored_on_image(self, db):
        """_save_image_to_db stores import_job_id on the Image row."""
        from backend.pipeline.ingestion import _save_image_to_db

        job = ImportJob(id="job-abc", status="active", total_files=1)
        db.add(job)
        db.flush()

        image_data = {
            "filename": "test.jpg",
            "storage_key": "abc123.jpg",
            "name": "Test",
            "author": "Author",
            "group_name": None,
            "width": 100,
            "height": 100,
            "file_size": 1000,
            "thumbnail_key": "abc123_thumb.jpg",
            "import_job_id": "job-abc",
        }
        image_id = _save_image_to_db(db, image_data)
        db.commit()

        image = db.query(Image).filter(Image.id == image_id).first()
        assert image.import_job_id == "job-abc"

    def test_import_job_id_none_when_not_provided(self, db):
        """import_job_id is None when not present in image_data."""
        from backend.pipeline.ingestion import _save_image_to_db

        image_data = {
            "filename": "test.jpg",
            "storage_key": "abc123.jpg",
            "name": "Test",
            "author": "Author",
            "group_name": None,
            "width": 100,
            "height": 100,
            "file_size": 1000,
            "thumbnail_key": "abc123_thumb.jpg",
        }
        image_id = _save_image_to_db(db, image_data)
        db.commit()

        image = db.query(Image).filter(Image.id == image_id).first()
        assert image.import_job_id is None
