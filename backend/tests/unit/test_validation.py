"""Unit tests for upload validation helpers."""

import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image as PILImage

from backend.app.services.validation import check_zip_safety, verify_image_mime


def _make_jpeg_bytes(width: int = 20, height: int = 20) -> bytes:
    img = PILImage.new("RGB", (width, height), (100, 150, 200))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


def _make_zip(tmp_path: Path, files: dict[str, bytes]) -> Path:
    """Create a ZIP file containing the given filename→content pairs."""
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            info = zipfile.ZipInfo(name)
            info.file_size = len(data)
            zf.writestr(info, data)
    return zip_path


class TestCheckZipSafety:
    def test_valid_zip_passes(self, tmp_path):
        jpeg = _make_jpeg_bytes()
        zp = _make_zip(tmp_path, {"a.jpg": jpeg, "b.jpg": jpeg})
        # Should not raise
        check_zip_safety(zp, max_files=10, max_uncompressed_bytes=10 * 1024 * 1024)

    def test_too_many_files_rejected(self, tmp_path):
        jpeg = _make_jpeg_bytes()
        files = {f"{i}.jpg": jpeg for i in range(5)}
        zp = _make_zip(tmp_path, files)
        with pytest.raises(ValueError, match="limit is 3"):
            check_zip_safety(zp, max_files=3, max_uncompressed_bytes=10 * 1024 * 1024)

    def test_zip_bomb_rejected(self, tmp_path):
        # Create a 100KB file but set the limit to 50KB
        big_data = b"x" * 100_000
        zp = _make_zip(tmp_path, {"big.jpg": big_data})
        with pytest.raises(ValueError, match="exceeds limit"):
            check_zip_safety(zp, max_files=10, max_uncompressed_bytes=50_000)

    def test_invalid_zip_raises(self, tmp_path):
        bad_zip = tmp_path / "bad.zip"
        bad_zip.write_bytes(b"this is not a zip file")
        with pytest.raises(ValueError, match="Invalid or corrupt"):
            check_zip_safety(bad_zip, max_files=10, max_uncompressed_bytes=10 * 1024 * 1024)


class TestVerifyImageMime:
    def test_valid_jpeg_accepted(self):
        assert verify_image_mime(_make_jpeg_bytes()) is True

    def test_valid_png_accepted(self):
        img = PILImage.new("RGB", (20, 20), (0, 128, 255))
        buf = BytesIO()
        img.save(buf, format="PNG")
        assert verify_image_mime(buf.getvalue()) is True

    def test_text_file_rejected(self):
        assert verify_image_mime(b"Hello, world! This is not an image.") is False

    def test_executable_rejected(self):
        # MZ header (Windows PE executable)
        fake_exe = b"MZ" + b"\x00" * 100
        assert verify_image_mime(fake_exe) is False

    def test_empty_bytes_rejected(self):
        assert verify_image_mime(b"") is False

    def test_truncated_jpeg_rejected(self):
        # A JPEG starts with FF D8 but truncated mid-stream should fail verify
        assert verify_image_mime(b"\xff\xd8\xff\xe0" + b"\x00" * 10) is False
