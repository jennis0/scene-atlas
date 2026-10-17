"""Upload validation helpers for the import API.

Provides two utilities:
- check_zip_safety: reject ZIP files that exceed size/count limits before extraction
- verify_image_mime: confirm a file is a real image, not a renamed binary
"""

import logging
import warnings
from pathlib import Path
from zipfile import BadZipFile, ZipFile

logger = logging.getLogger(__name__)


def check_zip_safety(zip_path: Path, max_files: int, max_uncompressed_bytes: int) -> None:
    """Raise ValueError if the ZIP is invalid or exceeds the file-count or uncompressed-size limits.

    Must be called *before* extraction to prevent ZIP bombs filling the disk.
    """
    try:
        with ZipFile(zip_path, "r") as zf:
            entries = zf.infolist()

            # Check for path traversal in member names (zip-slip)
            for entry in entries:
                if entry.is_dir():
                    continue
                name = entry.filename
                member = Path(name)
                # Check absolute paths (both OS-native and Unix-style for portability)
                if member.is_absolute() or name.startswith("/"):
                    raise ValueError(f"Path traversal detected in ZIP member: {name}")
                if ".." in member.parts:
                    raise ValueError(f"Path traversal detected in ZIP member: {name}")

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


def verify_media_mime(source: "bytes | Path", ext: str) -> bool:
    """Verify file content matches its claimed extension.

    *source* may be raw bytes (legacy callers) or a Path to a file on disk
    (preferred — avoids holding the full file in memory).

    Routes to video or image verification based on extension.
    """
    from backend.app.config import settings

    if ext.lower() in settings.supported_video_formats:
        from backend.app.services.video_utils import verify_video_mime

        if isinstance(source, Path):
            # Video check only needs the first 8 bytes.
            with open(source, "rb") as f:
                header = f.read(8)
            return verify_video_mime(header)
        return verify_video_mime(source)
    return verify_image_mime(source)


def verify_image_mime(source: "bytes | Path") -> bool:
    """Return True if *source* is a valid image file, False otherwise.

    *source* may be raw bytes or a Path to a file on disk.

    Uses PIL to inspect the file header without fully decoding pixel data.
    This catches renamed executables, text files, and other non-images
    that have a supported extension (e.g. a .jpg that is actually a PDF).

    Returns False rather than raising so callers can skip invalid files
    with a warning rather than aborting the whole upload.
    """
    from PIL import Image, UnidentifiedImageError

    try:
        # Suppress DecompressionBombWarning here: this function only checks
        # whether the file *is* a valid image, not whether it is safe to
        # process at full resolution.  Oversized images are valid uploads;
        # the pipeline enforces size limits later with proper per-file context.
        # Without this, the global "warning → error" filter in logging_config
        # causes valid large battlemaps (100M+ px) to be silently rejected with
        # a misleading "bad magic bytes" log entry.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            if isinstance(source, Path):
                img = Image.open(source)
            else:
                from io import BytesIO

                img = Image.open(BytesIO(source))
            img.verify()
        return True
    except (UnidentifiedImageError, Exception):
        return False
