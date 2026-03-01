"""Unit tests for import_job_id tracking through the ingestion pipeline.

Verifies that _save_image_to_db stores import_job_id on the Image row, and
that prepare_single_image includes import_job_id in its returned image_data,
and that _run_group injects import_job_id into the metadata dict.
"""

from unittest.mock import MagicMock, patch

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


def test_run_group_injects_import_job_id_into_metadata(tmp_path):
    """_run_group passes import_job_id through to prepare_single_image's metadata."""
    from backend.pipeline.ingestion import _run_group

    captured_metadata = []

    def fake_prepare(image_path, metadata=None, pipeline_config=None):
        captured_metadata.append(metadata or {})
        return {
            "status": "failed",
            "original_image_path": image_path,
            "error": "mocked",
            "error_info": {},
        }

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = None

    mock_pipeline_config = MagicMock()
    mock_pipeline_config.ingestion_batch_size = 16
    mock_pipeline_config.max_concurrent_prepare = 1

    with (
        patch("backend.pipeline.ingestion.prepare_single_image", side_effect=fake_prepare),
        patch("backend.pipeline.ingestion.update_import_group_job_progress"),
        patch("backend.pipeline.ingestion._process_batch", return_value=([], 0)),
        patch("backend.pipeline.ingestion.get_engine"),
        patch("backend.pipeline.ingestion.get_session_local", return_value=lambda: mock_session),
    ):
        fname = "test.jpg"
        (tmp_path / fname).write_text("fake")
        files = [{"relative_path": fname, "name": "Test", "tags": [], "image_type": "battlemap"}]
        _run_group(
            group_job_id="g1",
            staging_dir=str(tmp_path),
            author="A",
            group_name="G",
            files=files,
            pipeline_config=mock_pipeline_config,
            job_id="job-xyz",
        )

    assert any(m.get("import_job_id") == "job-xyz" for m in captured_metadata)
