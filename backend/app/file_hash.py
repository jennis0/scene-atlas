"""SHA-256 of a file's bytes, streamed.

Dependency-free so ingest (byte duplicates), the model download (``vision_sha256``) and
the image-type classifier (which keys its heads on that hash) share one implementation.
"""

import hashlib
from pathlib import Path

_CHUNK = 1024 * 1024


def file_sha256(path: Path) -> str:
    """SHA-256 hex digest of a file's bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()
