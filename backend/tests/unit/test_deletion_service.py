"""Unit tests for safe_delete_image() and cleanup_import_images()."""

from unittest.mock import MagicMock, patch

import pytest

from backend.app.models.database import Color, Image, ImportJob, Tag
from backend.app.services.deletion_service import (
    _delete_all_thumbnails,
    cleanup_import_images,
    safe_delete_image,
)
from backend.app.services.image_store import ImageStore


def _make_image(storage_key: str, thumbnail_key: str | None = None, **kwargs) -> Image:
    """Create a minimal Image ORM object for test DB insertion."""
    return Image(
        name=kwargs.get("name", "TestMap"),
        filename=kwargs.get("filename", "TestMap.jpg"),
        author=kwargs.get("author", "TestAuthor"),
        storage_key=storage_key,
        thumbnail_key=thumbnail_key,
        media_type="image",
        image_type="battlemap",
    )


def _seed_store(store: ImageStore, key: str, content: bytes = b"data") -> None:
    """Write a file into the store so it exists on disk."""
    store.put_bytes(key, content)


@pytest.fixture
def stores(tmp_path):
    """Real ImageStore + ThumbnailStore backed by tmp_path."""
    image_store = ImageStore(tmp_path / "images")
    thumbnail_store = ImageStore(tmp_path / "thumbnails")
    return image_store, thumbnail_store


@pytest.fixture
def mock_qdrant():
    """Patch get_qdrant_service to return a mock with delete_image_embedding."""
    mock_svc = MagicMock()
    with patch("backend.app.services.qdrant_service.get_qdrant_service", return_value=mock_svc):
        yield mock_svc.delete_image_embedding


def _patch_stores(monkeypatch, image_store: ImageStore, thumbnail_store: ImageStore):
    """Make deletion_service use the provided test stores.

    safe_delete_image() does `from . import get_image_store` inside the
    function body, so we patch at the services package level.
    """
    monkeypatch.setattr(
        "backend.app.services.get_image_store",
        lambda: image_store,
    )
    monkeypatch.setattr(
        "backend.app.services.get_thumbnail_store",
        lambda: thumbnail_store,
    )


class TestSafeDeleteImageFileCleanup:
    """Physical file deletion behaviour based on ref-counting."""

    def test_unique_key_file_deleted(self, db_session, stores, monkeypatch, mock_qdrant):
        """When no other image shares the storage_key the file is removed from disk."""
        image_store, thumbnail_store = stores
        _patch_stores(monkeypatch, image_store, thumbnail_store)

        storage_key = "a1b2c3.jpg"
        _seed_store(image_store, storage_key)

        img = _make_image(storage_key)
        db_session.add(img)
        db_session.commit()

        safe_delete_image(db_session, img)
        db_session.commit()

        assert not image_store.exists(storage_key)

    def test_shared_key_file_kept_after_first_delete(
        self, db_session, stores, monkeypatch, mock_qdrant
    ):
        """When another image shares storage_key the file must NOT be deleted."""
        image_store, thumbnail_store = stores
        _patch_stores(monkeypatch, image_store, thumbnail_store)

        storage_key = "shared.jpg"
        _seed_store(image_store, storage_key)

        img1 = _make_image(storage_key, name="Map A", filename="MapA.jpg")
        img2 = _make_image(storage_key, name="Map B", filename="MapB.jpg")
        db_session.add_all([img1, img2])
        db_session.commit()

        safe_delete_image(db_session, img1)
        db_session.commit()

        # File must still exist because img2 still references it
        assert image_store.exists(storage_key)

    def test_shared_key_file_deleted_after_last_delete(
        self, db_session, stores, monkeypatch, mock_qdrant
    ):
        """After both sharing images are deleted the file is removed."""
        image_store, thumbnail_store = stores
        _patch_stores(monkeypatch, image_store, thumbnail_store)

        storage_key = "shared2.jpg"
        _seed_store(image_store, storage_key)

        img1 = _make_image(storage_key, name="Map X", filename="MapX.jpg")
        img2 = _make_image(storage_key, name="Map Y", filename="MapY.jpg")
        db_session.add_all([img1, img2])
        db_session.commit()

        safe_delete_image(db_session, img1)
        db_session.commit()

        # Re-fetch img2 so the session state is clean
        img2 = db_session.get(Image, img2.id)
        safe_delete_image(db_session, img2)
        db_session.commit()

        assert not image_store.exists(storage_key)


class TestSafeDeleteImageThumbnails:
    """Thumbnail deletion — all three size variants must be removed."""

    def test_all_thumbnail_sizes_deleted(self, db_session, stores, monkeypatch, mock_qdrant):
        """All three thumbnail sizes (150, 400, 800) are deleted when image is unique."""
        image_store, thumbnail_store = stores
        _patch_stores(monkeypatch, image_store, thumbnail_store)

        storage_key = "a1b2c3.jpg"
        thumb_stem = "a1b2c3"
        thumb_key = f"{thumb_stem}_400x400.jpg"

        _seed_store(image_store, storage_key)
        for size in ["150x150", "400x400", "800x800"]:
            _seed_store(thumbnail_store, f"{thumb_stem}_{size}.jpg")

        img = _make_image(storage_key, thumbnail_key=thumb_key)
        db_session.add(img)
        db_session.commit()

        safe_delete_image(db_session, img)
        db_session.commit()

        for size in ["150x150", "400x400", "800x800"]:
            assert not thumbnail_store.exists(f"{thumb_stem}_{size}.jpg")

    def test_missing_thumbnails_do_not_raise(self, db_session, stores, monkeypatch, mock_qdrant):
        """If thumbnail files are already gone, deletion must not raise an error."""
        image_store, thumbnail_store = stores
        _patch_stores(monkeypatch, image_store, thumbnail_store)

        storage_key = "b1b2b3.jpg"
        thumb_key = "b1b2b3_400x400.jpg"

        _seed_store(image_store, storage_key)
        # Deliberately do NOT seed thumbnails — they're already missing

        img = _make_image(storage_key, thumbnail_key=thumb_key)
        db_session.add(img)
        db_session.commit()

        # Must not raise
        safe_delete_image(db_session, img)
        db_session.commit()

    def test_no_thumbnail_key_no_thumbnail_deletion(
        self, db_session, stores, monkeypatch, mock_qdrant
    ):
        """If thumbnail_key is None the thumbnail store is never touched."""
        image_store, thumbnail_store = stores
        _patch_stores(monkeypatch, image_store, thumbnail_store)

        storage_key = "c1c2c3.jpg"
        _seed_store(image_store, storage_key)

        img = _make_image(storage_key, thumbnail_key=None)
        db_session.add(img)
        db_session.commit()

        safe_delete_image(db_session, img)
        db_session.commit()
        # No assertions needed — just checking it doesn't raise


class TestSafeDeleteImageDbCleanup:
    """DB record and associated tags/colors must be removed."""

    def test_image_record_deleted(self, db_session, stores, monkeypatch, mock_qdrant):
        image_store, thumbnail_store = stores
        _patch_stores(monkeypatch, image_store, thumbnail_store)
        _seed_store(image_store, "d1d2d3.jpg")

        img = _make_image("d1d2d3.jpg")
        db_session.add(img)
        db_session.commit()
        img_id = img.id

        safe_delete_image(db_session, img)
        db_session.commit()

        assert db_session.get(Image, img_id) is None

    def test_associated_tags_deleted(self, db_session, stores, monkeypatch, mock_qdrant):
        """Tags associated with the deleted image must be removed via cascade."""
        image_store, thumbnail_store = stores
        _patch_stores(monkeypatch, image_store, thumbnail_store)
        _seed_store(image_store, "e1e2e3.jpg")

        img = _make_image("e1e2e3.jpg")
        db_session.add(img)
        db_session.commit()

        tag = Tag(
            image_id=img.id, category="lighting", value="night", confidence=1.0, source="manual"
        )
        db_session.add(tag)
        db_session.commit()
        tag_id = tag.id

        safe_delete_image(db_session, img)
        db_session.commit()

        assert db_session.get(Tag, tag_id) is None

    def test_associated_colors_deleted(self, db_session, stores, monkeypatch, mock_qdrant):
        """Color rows associated with the deleted image must be removed via cascade."""
        image_store, thumbnail_store = stores
        _patch_stores(monkeypatch, image_store, thumbnail_store)
        _seed_store(image_store, "f1f2f3.jpg")

        img = _make_image("f1f2f3.jpg")
        db_session.add(img)
        db_session.commit()

        color = Color(image_id=img.id, color_hex="#ff0000", percentage=50.0, color_order=1)
        db_session.add(color)
        db_session.commit()
        color_id = color.id

        safe_delete_image(db_session, img)
        db_session.commit()

        assert db_session.get(Color, color_id) is None


class TestSafeDeleteImageQdrant:
    """Qdrant embedding must always be deleted, regardless of ref count."""

    def test_qdrant_delete_called_once(self, db_session, stores, monkeypatch, mock_qdrant):
        image_store, thumbnail_store = stores
        _patch_stores(monkeypatch, image_store, thumbnail_store)
        _seed_store(image_store, "g1g2g3.jpg")

        img = _make_image("g1g2g3.jpg")
        db_session.add(img)
        db_session.commit()
        img_id = img.id

        safe_delete_image(db_session, img)
        db_session.commit()

        mock_qdrant.assert_called_once_with(img_id)

    def test_qdrant_delete_called_even_when_shared_key(
        self, db_session, stores, monkeypatch, mock_qdrant
    ):
        """Even if the storage file is kept (shared key), the embedding is removed."""
        image_store, thumbnail_store = stores
        _patch_stores(monkeypatch, image_store, thumbnail_store)
        _seed_store(image_store, "h1h2h3.jpg")

        img1 = _make_image("h1h2h3.jpg", name="Map A", filename="MapA.jpg")
        img2 = _make_image("h1h2h3.jpg", name="Map B", filename="MapB.jpg")
        db_session.add_all([img1, img2])
        db_session.commit()
        img1_id = img1.id

        safe_delete_image(db_session, img1)
        db_session.commit()

        mock_qdrant.assert_called_once_with(img1_id)

    def test_qdrant_failure_does_not_raise(self, db_session, stores, monkeypatch):
        """A Qdrant error during deletion must be swallowed (logged, not raised)."""
        image_store, thumbnail_store = stores
        _patch_stores(monkeypatch, image_store, thumbnail_store)
        _seed_store(image_store, "i1i2i3.jpg")

        mock_svc = MagicMock()
        mock_svc.delete_image_embedding.side_effect = RuntimeError("qdrant down")
        with patch("backend.app.services.qdrant_service.get_qdrant_service", return_value=mock_svc):
            img = _make_image("i1i2i3.jpg")
            db_session.add(img)
            db_session.commit()

            # Must not raise despite Qdrant failure
            safe_delete_image(db_session, img)
            db_session.commit()

        # Image still removed from DB
        assert db_session.get(Image, img.id) is None


class TestDeleteAllThumbnails:
    """_delete_all_thumbnails() must delete all size variants for a stem."""

    def test_deletes_all_three_sizes(self, tmp_path):
        store = ImageStore(tmp_path / "thumbs")
        stem = "a1b2c3d4"
        for size in ["150x150", "400x400", "800x800"]:
            store.put_bytes(f"{stem}_{size}.jpg", b"thumb")

        _delete_all_thumbnails(store, f"{stem}_400x400.jpg")

        for size in ["150x150", "400x400", "800x800"]:
            assert not store.exists(f"{stem}_{size}.jpg")

    def test_missing_sizes_do_not_raise(self, tmp_path):
        """Only some sizes exist — function must not raise for missing ones."""
        store = ImageStore(tmp_path / "thumbs")
        stem = "b1b2b3b4"
        # Only seed the 400x400 size
        store.put_bytes(f"{stem}_400x400.jpg", b"thumb")

        # Should not raise even though 150 and 800 are missing
        _delete_all_thumbnails(store, f"{stem}_400x400.jpg")

    def test_malformed_key_deletes_fallback(self, tmp_path):
        """A thumbnail_key that doesn't match the {stem}_{size}.jpg pattern
        causes a fallback: just that one key is attempted for deletion."""
        store = ImageStore(tmp_path / "thumbs")
        key = "a1b2c3d4.jpg"  # No size suffix
        store.put_bytes(key, b"thumb")

        _delete_all_thumbnails(store, key)

        assert not store.exists(key)

    def test_malformed_key_fallback_store_raises_does_not_propagate(self, tmp_path):
        """If the fallback delete() raises, the exception is caught (lines 81-82)."""
        store = MagicMock()
        store.delete.side_effect = OSError("disk error")

        # Must not raise — exception is logged and swallowed
        _delete_all_thumbnails(store, "badkey.jpg")  # no {stem}_{size} pattern

    def test_size_variant_delete_raises_does_not_propagate(self, tmp_path):
        """If delete() raises on a size variant (lines 90-91), it's swallowed."""
        store = MagicMock()
        store.delete.side_effect = OSError("disk error")

        # Valid pattern key — exercises the per-size loop with exceptions
        _delete_all_thumbnails(store, "a1b2c3d4_400x400.jpg")


class TestSafeDeleteImageStoreError:
    """Lines 55-56: image_store.delete() failure must be swallowed."""

    def test_image_store_delete_failure_does_not_raise(
        self, db_session, stores, monkeypatch, mock_qdrant
    ):
        image_store, thumbnail_store = stores
        _patch_stores(monkeypatch, image_store, thumbnail_store)

        storage_key = "z1z2z3.jpg"
        img = _make_image(storage_key)
        db_session.add(img)
        db_session.commit()

        # Make delete() raise
        monkeypatch.setattr(
            image_store, "delete", lambda key: (_ for _ in ()).throw(OSError("gone"))
        )

        # Must not raise
        safe_delete_image(db_session, img)
        db_session.commit()

        # Image record is still removed from DB
        assert db_session.get(Image, img.id) is None


class TestCleanupImportImages:
    """cleanup_import_images() deletes all images for an import job."""

    def test_removes_all_images_for_job(self, db_session, stores, monkeypatch):
        """All Image rows for a job are deleted; count matches."""
        image_store, thumbnail_store = stores
        _patch_stores(monkeypatch, image_store, thumbnail_store)
        mock_qdrant_svc = MagicMock()
        mock_qdrant_svc.delete_embeddings = MagicMock()
        with patch(
            "backend.app.services.qdrant_service.get_qdrant_service",
            return_value=mock_qdrant_svc,
        ):
            job = ImportJob(id="test-job-1", status="failed", source_label="test")
            img_a = _make_image("key-a.jpg", filename="a.jpg", name="A")
            img_b = _make_image("key-b.jpg", filename="b.jpg", name="B")
            img_a.import_job_id = "test-job-1"
            img_b.import_job_id = "test-job-1"
            db_session.add_all([job, img_a, img_b])
            db_session.commit()

            count = cleanup_import_images("test-job-1", db_session)
            db_session.commit()

        assert count == 2
        remaining = db_session.query(Image).filter(Image.import_job_id == "test-job-1").all()
        assert remaining == []

    def test_returns_zero_for_empty_job(self, db_session, stores, monkeypatch):
        """Returns 0 and does nothing when no images exist for the job."""
        image_store, thumbnail_store = stores
        _patch_stores(monkeypatch, image_store, thumbnail_store)
        mock_qdrant_svc = MagicMock()
        with patch(
            "backend.app.services.qdrant_service.get_qdrant_service",
            return_value=mock_qdrant_svc,
        ):
            job = ImportJob(id="empty-job", status="failed", source_label="empty")
            db_session.add(job)
            db_session.commit()

            count = cleanup_import_images("empty-job", db_session)

        assert count == 0

    def test_deletes_physical_files_when_unique_key(self, db_session, stores, monkeypatch):
        """Physical files are removed when no other image shares the storage key."""
        image_store, thumbnail_store = stores
        _patch_stores(monkeypatch, image_store, thumbnail_store)
        mock_qdrant_svc = MagicMock()
        with patch(
            "backend.app.services.qdrant_service.get_qdrant_service",
            return_value=mock_qdrant_svc,
        ):
            _seed_store(image_store, "unique-key.jpg")
            job = ImportJob(id="file-job", status="failed", source_label="test")
            img = _make_image("unique-key.jpg", filename="u.jpg", name="U")
            img.import_job_id = "file-job"
            db_session.add_all([job, img])
            db_session.commit()

            cleanup_import_images("file-job", db_session)
            db_session.commit()

        assert not image_store.exists("unique-key.jpg")

    def test_deletes_all_thumbnail_sizes(self, db_session, stores, monkeypatch):
        """cleanup_import_images removes all three thumbnail size variants, not just one."""
        image_store, thumbnail_store = stores
        _patch_stores(monkeypatch, image_store, thumbnail_store)
        mock_qdrant_svc = MagicMock()
        with patch(
            "backend.app.services.qdrant_service.get_qdrant_service",
            return_value=mock_qdrant_svc,
        ):
            stem = "tkey"
            thumb_key = f"{stem}_400x400.jpg"
            _seed_store(image_store, "tk.jpg")
            for size in ["150x150", "400x400", "800x800"]:
                _seed_store(thumbnail_store, f"{stem}_{size}.jpg")

            job = ImportJob(id="thumb-job", status="failed", source_label="test")
            img = _make_image("tk.jpg", thumbnail_key=thumb_key, filename="tk.jpg", name="TK")
            img.import_job_id = "thumb-job"
            db_session.add_all([job, img])
            db_session.commit()

            cleanup_import_images("thumb-job", db_session)
            db_session.commit()

        for size in ["150x150", "400x400", "800x800"]:
            assert not thumbnail_store.exists(f"{stem}_{size}.jpg"), f"{size} thumbnail not deleted"

    def test_qdrant_failure_does_not_raise(self, db_session, stores, monkeypatch):
        """Qdrant errors during batch cleanup are swallowed."""
        image_store, thumbnail_store = stores
        _patch_stores(monkeypatch, image_store, thumbnail_store)
        mock_qdrant_svc = MagicMock()
        mock_qdrant_svc.delete_embeddings.side_effect = RuntimeError("qdrant down")
        with patch(
            "backend.app.services.qdrant_service.get_qdrant_service",
            return_value=mock_qdrant_svc,
        ):
            job = ImportJob(id="qdrant-fail-job", status="failed", source_label="test")
            img = _make_image("qfail.jpg", filename="qf.jpg", name="QF")
            img.import_job_id = "qdrant-fail-job"
            db_session.add_all([job, img])
            db_session.commit()

            # Must not raise
            count = cleanup_import_images("qdrant-fail-job", db_session)
            db_session.commit()

        assert count == 1
