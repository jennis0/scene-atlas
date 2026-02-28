"""Unit tests for upload validation helpers."""

import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image as PILImage

from backend.app.services.validation import check_zip_safety, verify_image_mime, verify_media_mime
from backend.app.services.video_utils import verify_video_mime


def _make_jpeg_bytes(width: int = 20, height: int = 20) -> bytes:
    img = PILImage.new("RGB", (width, height), (100, 150, 200))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


def _make_png_bytes() -> bytes:
    img = PILImage.new("RGB", (20, 20), (0, 128, 255))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_webp_bytes() -> bytes:
    img = PILImage.new("RGB", (20, 20), (0, 128, 255))
    buf = BytesIO()
    img.save(buf, format="WEBP")
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


def _make_mp4_magic(ftyp_brand: bytes = b"isom") -> bytes:
    """Create minimal bytes with an MP4 'ftyp' box at offset 4."""
    # Minimal ftyp box: [4-byte size][b"ftyp"][4-byte major brand][4-byte minor version]...
    box_size = (16).to_bytes(4, "big")
    return box_size + b"ftyp" + ftyp_brand + b"\x00" * 64


def _make_webm_magic() -> bytes:
    """Create minimal bytes with a WebM/Matroska EBML header at offset 0."""
    return b"\x1a\x45\xdf\xa3" + b"\x00" * 64


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

    def test_at_exact_file_limit_passes(self, tmp_path):
        """n files at exactly the limit must pass (boundary: equal is allowed)."""
        jpeg = _make_jpeg_bytes()
        files = {f"{i}.jpg": jpeg for i in range(5)}
        zp = _make_zip(tmp_path, files)
        check_zip_safety(zp, max_files=5, max_uncompressed_bytes=10 * 1024 * 1024)

    def test_one_over_file_limit_rejected(self, tmp_path):
        """n+1 files must be rejected (boundary: one over is rejected)."""
        jpeg = _make_jpeg_bytes()
        files = {f"{i}.jpg": jpeg for i in range(4)}
        zp = _make_zip(tmp_path, files)
        with pytest.raises(ValueError, match="limit is 3"):
            check_zip_safety(zp, max_files=3, max_uncompressed_bytes=10 * 1024 * 1024)

    def test_at_exact_byte_limit_passes(self, tmp_path):
        """Total uncompressed bytes at exactly the limit must pass."""
        data = b"x" * 1000
        zp = _make_zip(tmp_path, {"a.bin": data})
        check_zip_safety(zp, max_files=10, max_uncompressed_bytes=1000)

    def test_one_byte_over_limit_rejected(self, tmp_path):
        """Total uncompressed bytes one over the limit must be rejected."""
        data = b"x" * 1001
        zp = _make_zip(tmp_path, {"a.bin": data})
        with pytest.raises(ValueError, match="exceeds limit"):
            check_zip_safety(zp, max_files=10, max_uncompressed_bytes=1000)

    def test_directories_not_counted_as_files(self, tmp_path):
        """Zip directory entries must not count toward the file limit."""
        zip_path = tmp_path / "with_dirs.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            # Add a directory entry
            zf.mkdir("subdir/")
            # Add one real file
            zf.writestr("subdir/file.jpg", _make_jpeg_bytes())
        # Only 1 file — must pass with limit 1
        check_zip_safety(zip_path, max_files=1, max_uncompressed_bytes=10 * 1024 * 1024)

    def test_zip_with_path_traversal_member_rejected(self, tmp_path):
        """ZIP member names with ../ path traversal must be rejected."""
        zip_path = tmp_path / "evil.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            info = zipfile.ZipInfo("../../etc/passwd")
            info.file_size = 5
            zf.writestr(info, b"evil!")
        with pytest.raises(ValueError, match="[Pp]ath traversal"):
            check_zip_safety(zip_path, max_files=10, max_uncompressed_bytes=10 * 1024 * 1024)

    def test_zip_with_absolute_path_member_rejected(self, tmp_path):
        """ZIP member names with absolute paths must be rejected."""
        zip_path = tmp_path / "evil.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            info = zipfile.ZipInfo("/etc/passwd")
            info.file_size = 5
            zf.writestr(info, b"evil!")
        with pytest.raises(ValueError, match="[Pp]ath traversal"):
            check_zip_safety(zip_path, max_files=10, max_uncompressed_bytes=10 * 1024 * 1024)


class TestVerifyImageMime:
    def test_valid_jpeg_accepted(self):
        assert verify_image_mime(_make_jpeg_bytes()) is True

    def test_valid_png_accepted(self):
        assert verify_image_mime(_make_png_bytes()) is True

    def test_valid_webp_accepted(self):
        assert verify_image_mime(_make_webp_bytes()) is True

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

    def test_pdf_bytes_rejected(self):
        # PDF magic bytes: %PDF-
        fake_pdf = b"%PDF-1.4 fake content" + b"\x00" * 100
        assert verify_image_mime(fake_pdf) is False

    def test_zip_bytes_rejected(self):
        # ZIP magic bytes: PK\x03\x04
        fake_zip = b"PK\x03\x04" + b"\x00" * 100
        assert verify_image_mime(fake_zip) is False

    def test_elf_binary_rejected(self):
        # ELF magic bytes (Linux executable)
        fake_elf = b"\x7fELF" + b"\x00" * 100
        assert verify_image_mime(fake_elf) is False

    def test_content_checked_not_extension(self):
        """JPEG bytes are accepted; the function checks content, not filename extension."""
        assert verify_image_mime(_make_jpeg_bytes()) is True
        assert verify_image_mime(_make_png_bytes()) is True


class TestVerifyVideoMime:
    """Tests for verify_video_mime — magic bytes only, no full decode."""

    def test_mp4_with_isom_brand_accepted(self):
        assert verify_video_mime(_make_mp4_magic(b"isom")) is True

    def test_mp4_with_mp42_brand_accepted(self):
        assert verify_video_mime(_make_mp4_magic(b"mp42")) is True

    def test_mp4_with_m4v_brand_accepted(self):
        # iTunes video format (M4V space-padded to 4 bytes)
        assert verify_video_mime(_make_mp4_magic(b"M4V ")) is True

    def test_webm_ebml_header_accepted(self):
        assert verify_video_mime(_make_webm_magic()) is True

    def test_random_bytes_rejected(self):
        assert verify_video_mime(b"\x00\x01\x02\x03\x04\x05\x06\x07" * 16) is False

    def test_data_less_than_8_bytes_rejected(self):
        # The check requires len(data) >= 8 before inspecting magic bytes
        assert verify_video_mime(b"ftyp") is False  # 4 bytes

    def test_exactly_7_bytes_rejected(self):
        # One byte short of the minimum 8-byte requirement
        assert verify_video_mime(b"1234567") is False

    def test_empty_data_rejected(self):
        assert verify_video_mime(b"") is False

    def test_png_data_rejected_as_video(self):
        # Valid PNG is not a valid video
        assert verify_video_mime(_make_png_bytes()) is False

    def test_jpeg_data_rejected_as_video(self):
        # Valid JPEG is not a valid video
        assert verify_video_mime(_make_jpeg_bytes()) is False

    def test_ftyp_at_wrong_offset_rejected(self):
        # 'ftyp' at offset 0 (not 4) must not match the MP4 check
        data = b"ftyp" + b"isom" + b"\x00" * 64
        assert verify_video_mime(data) is False

    def test_partial_webm_header_rejected(self):
        # Only first 3 of 4 EBML bytes present
        assert verify_video_mime(b"\x1a\x45\xdf" + b"\x00" * 16) is False


class TestVerifyMediaMime:
    """verify_media_mime routes to video or image MIME check based on extension."""

    def test_jpeg_with_jpg_ext_accepted(self):
        assert verify_media_mime(_make_jpeg_bytes(), ".jpg") is True

    def test_jpeg_with_jpeg_ext_accepted(self):
        assert verify_media_mime(_make_jpeg_bytes(), ".jpeg") is True

    def test_png_with_png_ext_accepted(self):
        assert verify_media_mime(_make_png_bytes(), ".png") is True

    def test_webp_with_webp_ext_accepted(self):
        assert verify_media_mime(_make_webp_bytes(), ".webp") is True

    def test_mp4_with_mp4_ext_accepted(self):
        assert verify_media_mime(_make_mp4_magic(), ".mp4") is True

    def test_webm_with_webm_ext_accepted(self):
        assert verify_media_mime(_make_webm_magic(), ".webm") is True

    def test_invalid_image_bytes_rejected(self):
        assert verify_media_mime(b"not an image" * 20, ".jpg") is False

    def test_invalid_video_bytes_rejected(self):
        assert verify_media_mime(b"\x00" * 64, ".mp4") is False

    def test_image_bytes_with_video_ext_rejected(self):
        # PNG bytes routed through video check → wrong magic → rejected
        assert verify_media_mime(_make_png_bytes(), ".mp4") is False

    def test_ext_check_is_case_insensitive(self):
        # .MP4 and .WEBM must route to video check just like lowercase
        assert verify_media_mime(_make_mp4_magic(), ".MP4") is True
        assert verify_media_mime(_make_webm_magic(), ".WEBM") is True
