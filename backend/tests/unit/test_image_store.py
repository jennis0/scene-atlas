"""Unit tests for the ImageStore hash-sharded filesystem storage."""

from pathlib import Path

import pytest

from backend.app.services.image_store import ImageStore


class TestKeyToPath:
    """_key_to_path() must shard keys into a two-level directory hierarchy."""

    def test_sharding_structure(self, tmp_path):
        store = ImageStore(tmp_path)
        result = store._key_to_path("a1b2c3d4e5f6.jpg")
        assert result == tmp_path / "a1" / "b2" / "a1b2c3d4e5f6.jpg"

    def test_short_key_uses_first_four_chars(self, tmp_path):
        store = ImageStore(tmp_path)
        result = store._key_to_path("abcd.png")
        assert result == tmp_path / "ab" / "cd" / "abcd.png"

    def test_extension_preserved_in_filename(self, tmp_path):
        store = ImageStore(tmp_path)
        for ext in (".jpg", ".png", ".webp", ".mp4"):
            result = store._key_to_path(f"a1b2c3{ext}")
            assert result.name.endswith(ext)

    def test_different_keys_produce_different_paths(self, tmp_path):
        store = ImageStore(tmp_path)
        p1 = store._key_to_path("aaaabbbb.jpg")
        p2 = store._key_to_path("ccccdddd.jpg")
        assert p1 != p2

    def test_shard_dirs_are_under_base(self, tmp_path):
        store = ImageStore(tmp_path)
        result = store._key_to_path("a1b2c3d4.jpg")
        assert str(result).startswith(str(tmp_path))


class TestPut:
    """put() must copy a source file into the sharded store."""

    def test_file_is_copied(self, tmp_path):
        store_dir = tmp_path / "store"
        source = tmp_path / "source.jpg"
        source.write_bytes(b"fake jpeg data")

        store = ImageStore(store_dir)
        dest = store.put("a1b2c3d4.jpg", source)

        assert dest.exists()

    def test_content_preserved(self, tmp_path):
        store_dir = tmp_path / "store"
        content = b"\xff\xd8\xff\xe0" + b"\x00" * 20  # JPEG-ish bytes
        source = tmp_path / "img.jpg"
        source.write_bytes(content)

        store = ImageStore(store_dir)
        dest = store.put("a1b2c3.jpg", source)

        assert dest.read_bytes() == content

    def test_creates_parent_directories(self, tmp_path):
        store_dir = tmp_path / "store"
        source = tmp_path / "src.jpg"
        source.write_bytes(b"data")

        store = ImageStore(store_dir)
        dest = store.put("a1b2c3.jpg", source)

        # Shard dirs must exist
        assert (store_dir / "a1" / "b2").is_dir()
        assert dest.parent.is_dir()

    def test_returns_correct_path(self, tmp_path):
        store_dir = tmp_path / "store"
        source = tmp_path / "src.jpg"
        source.write_bytes(b"data")

        store = ImageStore(store_dir)
        returned = store.put("a1b2c3d4.jpg", source)
        expected = store._key_to_path("a1b2c3d4.jpg")

        assert returned == expected


class TestPutBytes:
    """put_bytes() must write raw bytes directly into the sharded store."""

    def test_file_created_with_correct_content(self, tmp_path):
        store = ImageStore(tmp_path / "store")
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16  # PNG-ish header
        dest = store.put_bytes("a1b2c3.png", content)
        assert dest.read_bytes() == content

    def test_creates_parent_directories(self, tmp_path):
        store = ImageStore(tmp_path / "store")
        store.put_bytes("a1b2c3.jpg", b"data")
        assert (tmp_path / "store" / "a1" / "b2").is_dir()

    def test_returns_sharded_path(self, tmp_path):
        store = ImageStore(tmp_path / "store")
        returned = store.put_bytes("a1b2c3d4.jpg", b"x")
        assert returned == store._key_to_path("a1b2c3d4.jpg")


class TestExists:
    """exists() must reflect the actual filesystem state."""

    def test_returns_false_for_missing_key(self, tmp_path):
        store = ImageStore(tmp_path)
        assert store.exists("nonexistent.jpg") is False

    def test_returns_true_after_put_bytes(self, tmp_path):
        store = ImageStore(tmp_path)
        key = "a1b2c3.jpg"
        store.put_bytes(key, b"data")
        assert store.exists(key) is True

    def test_returns_false_after_delete(self, tmp_path):
        store = ImageStore(tmp_path)
        key = "a1b2c3.jpg"
        store.put_bytes(key, b"data")
        store.delete(key)
        assert store.exists(key) is False


class TestDelete:
    """delete() must remove files and return the correct boolean status."""

    def test_deletes_existing_file_and_returns_true(self, tmp_path):
        store = ImageStore(tmp_path)
        key = "a1b2c3.jpg"
        store.put_bytes(key, b"data")
        assert store.delete(key) is True
        assert not store._key_to_path(key).exists()

    def test_returns_false_for_missing_key(self, tmp_path):
        store = ImageStore(tmp_path)
        assert store.delete("doesnotexist.jpg") is False

    def test_idempotent_second_delete_returns_false(self, tmp_path):
        store = ImageStore(tmp_path)
        key = "a1b2c3.jpg"
        store.put_bytes(key, b"data")
        assert store.delete(key) is True
        assert store.delete(key) is False


class TestGenerateKey:
    """generate_key() must produce a unique UUID-based key with the correct extension."""

    def test_extension_preserved_lowercase(self):
        key = ImageStore.generate_key("photo.JPG")
        assert key.endswith(".jpg"), f"expected .jpg suffix, got: {key}"

    def test_webp_extension(self):
        assert ImageStore.generate_key("image.webp").endswith(".webp")

    def test_mp4_extension(self):
        assert ImageStore.generate_key("video.mp4").endswith(".mp4")

    def test_keys_are_unique(self):
        keys = {ImageStore.generate_key("x.jpg") for _ in range(50)}
        assert len(keys) == 50

    def test_key_has_uuid_length(self):
        # UUID hex = 32 chars + 4-char extension = 36 chars minimum
        key = ImageStore.generate_key("test.jpg")
        stem = Path(key).stem
        assert len(stem) == 32  # UUID hex has exactly 32 hex chars

    def test_key_does_not_contain_path_separators(self):
        key = ImageStore.generate_key("some/nested/path/image.png")
        assert "/" not in key
        assert "\\" not in key


class TestGetPath:
    """get_path() must return the sharded path without requiring the file to exist."""

    def test_returns_sharded_path(self, tmp_path):
        store = ImageStore(tmp_path)
        path = store.get_path("a1b2c3d4.jpg")
        assert path == tmp_path / "a1" / "b2" / "a1b2c3d4.jpg"

    def test_path_does_not_need_to_exist(self, tmp_path):
        store = ImageStore(tmp_path)
        path = store.get_path("nonexistent.jpg")
        assert isinstance(path, Path)
