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
        from backend.pipeline.persistence import _save_image_to_db

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
        from backend.pipeline.persistence import _save_image_to_db

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
    # Make mock_session a context manager
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    mock_pipeline_config = MagicMock()
    mock_pipeline_config.ingestion_batch_size = 16
    mock_pipeline_config.max_concurrent_prepare = 1

    with (
        patch("backend.pipeline.ingestion.prepare_single_image", side_effect=fake_prepare),
        patch("backend.pipeline.ingestion.update_import_group_job_progress"),
        patch("backend.pipeline.ingestion._process_batch", return_value=([], 0, [])),
        patch("backend.pipeline.ingestion.pipeline_db", return_value=mock_session),
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


class TestPrepareUsesOriginalFilename:
    """prepare_single_image should use the original filename from relative_path,
    not the UUID-based staging path name."""

    def test_filename_from_relative_path_not_staging_key(self, tmp_path):
        """When image_path is a UUID staging key but relative_path has the
        original name, the returned filename should be the original."""
        from backend.pipeline.prepare import prepare_single_image

        # Simulate a staging file with a UUID hex name
        staging_key = "a1b2c3d4e5f6.jpg"
        staging_file = tmp_path / staging_key
        # Create a minimal valid JPEG (SOI + EOI markers)
        staging_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9")

        original_filename = "Forest - Winter - Day.jpg"

        with (
            patch("backend.pipeline.prepare.get_image_store") as mock_store,
            patch(
                "backend.pipeline.tasks.image_processing.generate_thumbnails",
                return_value={"keys": {"medium": "thumb.jpg"}, "dimensions": (100, 100)},
            ),
            patch(
                "backend.pipeline.tasks.color_extraction.extract_dominant_colors",
                return_value=[],
            ),
        ):
            mock_store.return_value.put = MagicMock()

            result = prepare_single_image(
                image_path=str(staging_file),
                metadata={
                    "author": "TestAuthor",
                    "group_name": "Forest",
                    "name": "Forest - Winter - Day",
                    "relative_path": original_filename,
                    "tags": [],
                    "image_type": "scene",
                },
            )

        assert result["status"] == "success"
        assert result["image_data"]["filename"] == original_filename
        assert result["vector_metadata"]["filename"] == original_filename

    def test_filename_falls_back_to_path_name_without_relative_path(self, tmp_path):
        """Without relative_path in metadata, filename should come from the
        image path itself."""
        from backend.pipeline.prepare import prepare_single_image

        image_file = tmp_path / "actual_image.jpg"
        image_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9")

        with (
            patch("backend.pipeline.prepare.get_image_store") as mock_store,
            patch(
                "backend.pipeline.tasks.image_processing.generate_thumbnails",
                return_value={"keys": {"medium": "thumb.jpg"}, "dimensions": (100, 100)},
            ),
            patch(
                "backend.pipeline.tasks.color_extraction.extract_dominant_colors",
                return_value=[],
            ),
        ):
            mock_store.return_value.put = MagicMock()

            result = prepare_single_image(
                image_path=str(image_file),
                metadata={
                    "author": "TestAuthor",
                    "group_name": "Test",
                    "name": "Test",
                    "tags": [],
                    "image_type": "scene",
                },
            )

        assert result["status"] == "success"
        assert result["image_data"]["filename"] == "actual_image.jpg"


def _make_image_data(group_name: str, author: str, storage_key: str) -> dict:
    return {
        "filename": f"{storage_key}.jpg",
        "storage_key": f"{storage_key}.jpg",
        "name": storage_key,
        "author": author,
        "group_name": group_name,
        "width": 100,
        "height": 100,
        "file_size": 1000,
    }


class TestBatchSaveGroupQueryCount:
    """batch_save_to_database should query the group table at most once per batch."""

    def test_group_queried_once_for_batch_of_three(self, db):
        """Three images in the same group trigger only one ImageGroup SELECT."""
        from backend.app.models.database import ImageGroup
        from backend.pipeline.persistence import _save_image_to_db

        query_call_count = 0
        original_query = db.query

        def counting_query(model):
            nonlocal query_call_count
            if model is ImageGroup:
                query_call_count += 1
            return original_query(model)

        db.query = counting_query

        batch = [_make_image_data("Group A", "Author", f"key-{i}") for i in range(3)]

        # Simulate what batch_save_to_database does: resolve group once, then pass it

        group_name = batch[0].get("group_name")
        author = batch[0].get("author")
        resolved_group = (
            db.query(ImageGroup)
            .filter(ImageGroup.base_name == group_name, ImageGroup.author == author)
            .first()
        )
        # Reset count after the initial resolve
        query_call_count = 0

        for image_data in batch:
            _save_image_to_db(db, image_data, group=resolved_group)
            if resolved_group is None:
                # Pick up newly created group from first image
                from backend.app.models.database import Image

                last_img = db.query(Image).order_by(Image.id.desc()).first()
                if last_img and last_img.group_id:
                    resolved_group = (
                        db.query(ImageGroup).filter(ImageGroup.id == last_img.group_id).first()
                    )
                    query_call_count = 0  # reset after first creation

        db.rollback()
        # With the group pre-resolved, _save_image_to_db must NOT issue extra queries
        assert query_call_count == 0, f"Expected 0 group queries, got {query_call_count}"

    def test_group_created_and_reused(self, db):
        """When a group doesn't exist yet, it's created on the first image and reused."""
        from backend.app.models.database import Image, ImageGroup
        from backend.pipeline.persistence import _save_image_to_db

        batch = [_make_image_data("New Group", "Bob", f"nk-{i}") for i in range(3)]

        # Initial resolve returns None (group doesn't exist yet)
        resolved_group = None
        for image_data in batch:
            _save_image_to_db(db, image_data, group=resolved_group)
            if resolved_group is None:
                last_img = db.query(Image).order_by(Image.id.desc()).first()
                if last_img and last_img.group_id:
                    resolved_group = (
                        db.query(ImageGroup).filter(ImageGroup.id == last_img.group_id).first()
                    )
        db.commit()

        # All 3 images should be in the same group
        images = db.query(Image).filter(Image.author == "Bob").all()
        assert len(images) == 3
        group_ids = {img.group_id for img in images}
        assert len(group_ids) == 1, f"Expected 1 group, got: {group_ids}"
