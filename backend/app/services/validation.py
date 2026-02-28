"""Upload validation helpers for the import API.

Provides two utilities:
- check_zip_safety: reject ZIP files that exceed size/count limits before extraction
- verify_image_mime: confirm a file is a real image, not a renamed binary
"""

import logging
from pathlib import Path
from zipfile import BadZipFile, ZipFile

logger = logging.getLogger(__name__)


def is_path_within(base_dir: Path, target: Path) -> bool:
    """Return True if *target* resolves to a path inside *base_dir*.

    Uses Path.relative_to() — immune to the adjacent-prefix false-positive
    that str.startswith() suffers from.
    """
    try:
        target.resolve().relative_to(base_dir.resolve())
        return True
    except ValueError:
        return False


def check_zip_safety(zip_path: Path, max_files: int, max_uncompressed_bytes: int) -> None:
    """Raise ValueError if ZIP exceeds file count or total uncompressed size.

    Must be called *before* extraction to prevent ZIP bombs filling the disk.

    Args:
        zip_path: Path to the already-saved ZIP file.
        max_files: Maximum number of extractable files.
        max_uncompressed_bytes: Maximum total uncompressed size in bytes.

    Raises:
        ValueError: If the ZIP is invalid or exceeds either limit.
    """
    try:
        with ZipFile(zip_path, "r") as zf:
            entries = zf.infolist()
            file_count = sum(1 for e in entries if not e.is_dir())
            total_uncompressed = sum(e.file_size for e in entries if not e.is_dir())
    except BadZipFile as exc:
        raise ValueError("Invalid or corrupt ZIP file") from exc

    if file_count > max_files:
        raise ValueError(f"ZIP contains {file_count} files; limit is {max_files}")
    if total_uncompressed > max_uncompressed_bytes:
        limit_mb = max_uncompressed_bytes // (1024 * 1024)
        actual_mb = total_uncompressed // (1024 * 1024)
        raise ValueError(f"ZIP uncompressed size ({actual_mb} MB) exceeds limit of {limit_mb} MB")


def verify_media_mime(data: bytes, ext: str) -> bool:
    """Verify file content matches its claimed extension.

    Routes to video or image verification based on extension.
    """
    from backend.app.config import settings

    if ext.lower() in settings.supported_video_formats:
        from backend.app.services.video_utils import verify_video_mime

        return verify_video_mime(data)
    return verify_image_mime(data)


def verify_image_mime(data: bytes) -> bool:
    """Return True if *data* is a valid image file, False otherwise.

    Uses PIL to inspect the file header without fully decoding pixel data.
    This catches renamed executables, text files, and other non-images
    that have a supported extension (e.g. a .jpg that is actually a PDF).

    Returns False rather than raising so callers can skip invalid files
    with a warning rather than aborting the whole upload.
    """
    from io import BytesIO

    from PIL import Image, UnidentifiedImageError

    try:
        img = Image.open(BytesIO(data))
        img.verify()
        return True
    except (UnidentifiedImageError, Exception):
        return False
