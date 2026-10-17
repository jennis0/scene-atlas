"""The maintenance and CLI pipeline scripts against a real SQLite DB and image store."""

import json

import pytest

from backend.app.models.database import Image, ImageGroup, Tag
from backend.app.services.image_store import ImageStore


@pytest.fixture
def library(tmp_db, tmp_path, monkeypatch, make_test_image):
    from backend.app import services

    engine, SessionLocal = tmp_db
    monkeypatch.setattr("backend.app.config.settings.database_url", str(engine.url))
    store = ImageStore(tmp_path / "library")
    monkeypatch.setattr(services, "_image_store", store)

    with SessionLocal() as db:
        group = ImageGroup(base_name="Forest Map", author="AuthorA")
        db.add(group)
        db.flush()
        for index, (filename, group_id) in enumerate(
            [("Forest_Night_winter.jpg", group.id), ("Cave.jpg", None)]
        ):
            key = f"aa/bb/img{index}.jpg"
            make_test_image(store.get_path(key), width=40, height=30)
            db.add(
                Image(
                    name=filename,
                    filename=filename,
                    author="AuthorA",
                    storage_key=key,
                    image_type="battlemap",
                    media_type="image",
                    width=40,
                    height=30,
                    group_id=group_id,
                )
            )
        db.commit()
    return SessionLocal


def test_backfill_content_hash(library):
    from backend.pipeline.backfill_content_hash import backfill_content_hash

    assert backfill_content_hash()["updated"] == 2
    with library() as db:
        assert all(img.content_hash for img in db.query(Image))


def test_retag_all_images_replaces_auto_tags(library):
    from backend.pipeline.retag_all_images import retag_all_images

    with library() as db:
        image = db.query(Image).filter_by(filename="Cave.jpg").one()
        db.add(Tag(image_id=image.id, category="x", value="stale", source="auto"))
        db.add(Tag(image_id=image.id, category="x", value="mine", source="manual"))
        db.commit()

    assert retag_all_images()["total"] == 2
    with library() as db:
        values = {t.value for t in db.query(Tag)}
    assert "stale" not in values and "mine" in values


def test_reparse_names_commits(library):
    from backend.pipeline.reparse_names import reparse_names

    assert reparse_names()["total"] == 2
    with library() as db:
        assert all(img.search_text for img in db.query(Image))


def test_fix_orphaned_images(library):
    from backend.pipeline.fix_orphaned_images import UNCATEGORISED_NAME, fix_orphaned_images

    fix_orphaned_images()
    with library() as db:
        assert db.query(Image).filter(Image.group_id.is_(None)).count() == 0
        assert db.query(ImageGroup).filter_by(base_name=UNCATEGORISED_NAME).count() == 1


def test_export_library(library, tmp_path):
    from backend.pipeline.export_library import export_library

    result = export_library(str(tmp_path / "out"))
    assert (result["exported"], result["skipped"]) == (2, 0)
    metadata = json.loads((tmp_path / "out" / "metadata.json").read_text())
    assert len(metadata["images"]) == 2
    assert all((tmp_path / "out" / arc).is_file() for arc in metadata["images"])


def test_backfill_grid_detection_runs(library):
    from backend.pipeline.backfill_grid_detection import backfill_grid_detection

    result = backfill_grid_detection()
    assert result["total"] == 2
    assert result["errors"] == 0
